import argparse
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser


DEFAULT_USER_AGENT = (
	"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
	"AppleWebKit/537.36 (KHTML, like Gecko) "
	"Chrome/125.0.0.0 Safari/537.36"
)


@dataclass
class NewsRecord:
	id: str
	source: str
	headline: str
	content: str
	url: str
	published_at: str | None
	fetched_at: str
	language: str
	ticker: str | None
	sentiment_score: float | None
	sentiment_label: str | None


@dataclass
class SourceConfig:
	name: str
	type: str
	enabled: bool
	list_url: str
	language: str = "zh-TW"
	timezone: str = "Asia/Taipei"
	max_items: int = 100
	timeout_seconds: int = 15
	retry_count: int = 2
	rate_limit_seconds: float = 1.0
	article_link_selector: str = "a"
	title_selector: str = "h1"
	time_selector: str = "time"
	content_selector: str = "p"
	base_url: str | None = None
	ticker_keywords: list[str] | None = None
	request_headers: dict[str, str] | None = None


def now_utc_iso() -> str:
	return datetime.now(tz=timezone.utc).isoformat()


def compact_text(text: str) -> str:
	return " ".join((text or "").split())


def parse_datetime_or_none(raw: str | None) -> str | None:
	if not raw:
		return None
	try:
		dt = date_parser.parse(raw)
		if not dt.tzinfo:
			dt = dt.replace(tzinfo=timezone.utc)
		return dt.astimezone(timezone.utc).isoformat()
	except (ValueError, OverflowError, TypeError):
		return None


def make_record_id(url: str, headline: str, published_at: str | None) -> str:
	key = f"{url}|{headline}|{published_at or ''}"
	return hashlib.sha256(key.encode("utf-8")).hexdigest()


class NewsScraper:
	def __init__(self, source_configs: list[SourceConfig], default_ticker: str | None = None):
		self.source_configs = source_configs
		self.default_ticker = default_ticker
		self.session = requests.Session()
		self.session.headers.update({"User-Agent": DEFAULT_USER_AGENT})
		self.seen_ids: set[str] = set()

	def _fetch_text(self, url: str, timeout_seconds: int, retry_count: int) -> str | None:
		for attempt in range(retry_count + 1):
			try:
				response = self.session.get(url, timeout=timeout_seconds)
				response.raise_for_status()
				return response.text
			except requests.RequestException:
				if attempt >= retry_count:
					return None
				time.sleep(1.5 ** attempt)
		return None

	def _match_keywords(self, text: str, source: SourceConfig) -> bool:
		keywords = source.ticker_keywords or []
		if not keywords:
			return True
		lowered_text = text.lower()
		return any(keyword.lower() in lowered_text for keyword in keywords)

	def _scrape_rss(self, source: SourceConfig) -> tuple[list[NewsRecord], dict[str, int]]:
		stats = {"fetched": 0, "deduped": 0, "filtered": 0, "errors": 0}
		xml_text = self._fetch_text(source.list_url, source.timeout_seconds, source.retry_count)
		if not xml_text:
			stats["errors"] += 1
			return [], stats

		soup = BeautifulSoup(xml_text, "html.parser")
		items = soup.find_all("item")[: source.max_items]
		records: list[NewsRecord] = []

		for item in items:
			title = compact_text(item.find_text("title", default=""))
			link = compact_text(item.find_text("link", default=""))
			pub_date = compact_text(item.find_text("pubdate", default=""))
			raw_description = item.find_text("description", default="")
			description = compact_text(BeautifulSoup(raw_description, "html.parser").get_text(" "))

			full_text = compact_text(f"{title} {description}")
			if not self._match_keywords(full_text, source):
				stats["filtered"] += 1
				continue

			published_at = parse_datetime_or_none(pub_date)
			record_id = make_record_id(link, title, published_at)
			if record_id in self.seen_ids:
				stats["deduped"] += 1
				continue

			self.seen_ids.add(record_id)
			record = NewsRecord(
				id=record_id,
				source=source.name,
				headline=title,
				content=description,
				url=link,
				published_at=published_at,
				fetched_at=now_utc_iso(),
				language=source.language,
				ticker=self.default_ticker,
				sentiment_score=None,
				sentiment_label=None,
			)
			records.append(record)
			stats["fetched"] += 1

		return records, stats

	def _scrape_html(self, source: SourceConfig) -> tuple[list[NewsRecord], dict[str, int]]:
		stats = {"fetched": 0, "deduped": 0, "filtered": 0, "errors": 0}
		list_html = self._fetch_text(source.list_url, source.timeout_seconds, source.retry_count)
		if not list_html:
			stats["errors"] += 1
			return [], stats

		list_soup = BeautifulSoup(list_html, "html.parser")
		anchors = list_soup.select(source.article_link_selector)
		links: list[str] = []
		base_url = source.base_url or source.list_url
		for anchor in anchors:
			href = anchor.get("href")
			if not href:
				continue
			links.append(urljoin(base_url, href))

		unique_links = list(dict.fromkeys(links))[: source.max_items]
		records: list[NewsRecord] = []

		for link in unique_links:
			article_html = self._fetch_text(link, source.timeout_seconds, source.retry_count)
			if not article_html:
				stats["errors"] += 1
				continue

			article_soup = BeautifulSoup(article_html, "html.parser")
			title = compact_text(article_soup.select_one(source.title_selector).get_text(" ")) if article_soup.select_one(source.title_selector) else ""
			time_raw = compact_text(article_soup.select_one(source.time_selector).get_text(" ")) if article_soup.select_one(source.time_selector) else ""
			content_nodes = article_soup.select(source.content_selector)
			content = compact_text(" ".join(node.get_text(" ") for node in content_nodes))
			full_text = compact_text(f"{title} {content}")

			if not self._match_keywords(full_text, source):
				stats["filtered"] += 1
				continue

			published_at = parse_datetime_or_none(time_raw)
			record_id = make_record_id(link, title, published_at)
			if record_id in self.seen_ids:
				stats["deduped"] += 1
				continue

			self.seen_ids.add(record_id)
			record = NewsRecord(
				id=record_id,
				source=source.name,
				headline=title,
				content=content,
				url=link,
				published_at=published_at,
				fetched_at=now_utc_iso(),
				language=source.language,
				ticker=self.default_ticker,
				sentiment_score=None,
				sentiment_label=None,
			)
			records.append(record)
			stats["fetched"] += 1
			time.sleep(max(0.0, source.rate_limit_seconds))

		return records, stats

	def run(self) -> tuple[list[NewsRecord], dict[str, dict[str, int]]]:
		all_records: list[NewsRecord] = []
		summary: dict[str, dict[str, int]] = {}

		for source in self.source_configs:
			if not source.enabled:
				continue

			if source.request_headers:
				self.session.headers.update(source.request_headers)

			if source.type == "rss":
				records, stats = self._scrape_rss(source)
			else:
				records, stats = self._scrape_html(source)

			all_records.extend(records)
			summary[source.name] = stats

		return all_records, summary


def load_source_configs(config_path: Path) -> list[SourceConfig]:
	payload = json.loads(config_path.read_text(encoding="utf-8"))
	if isinstance(payload, dict):
		source_items = payload.get("sources", [])
	else:
		source_items = payload

	configs: list[SourceConfig] = []
	for item in source_items:
		if not isinstance(item, dict):
			continue
		configs.append(
			SourceConfig(
				name=item.get("name", "unknown_source"),
				type=item.get("type", "rss").lower(),
				enabled=bool(item.get("enabled", False)),
				list_url=item.get("list_url", ""),
				language=item.get("language", "zh-TW"),
				timezone=item.get("timezone", "Asia/Taipei"),
				max_items=int(item.get("max_items", 100)),
				timeout_seconds=int(item.get("timeout_seconds", 15)),
				retry_count=int(item.get("retry_count", 2)),
				rate_limit_seconds=float(item.get("rate_limit_seconds", 1.0)),
				article_link_selector=item.get("article_link_selector", "a"),
				title_selector=item.get("title_selector", "h1"),
				time_selector=item.get("time_selector", "time"),
				content_selector=item.get("content_selector", "p"),
				base_url=item.get("base_url"),
				ticker_keywords=item.get("ticker_keywords"),
				request_headers=item.get("request_headers"),
			)
		)
	return [cfg for cfg in configs if cfg.list_url]


def write_jsonl(records: list[NewsRecord], output_path: Path, append: bool = False) -> None:
	output_path.parent.mkdir(parents=True, exist_ok=True)
	mode = "a" if append else "w"
	with output_path.open(mode, encoding="utf-8") as handle:
		for record in records:
			handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Config-driven news scraper for stock sentiment pipeline.")
	parser.add_argument(
		"--config",
		type=Path,
		default=Path("crawler/news_sources.json"),
		help="Path to source configuration JSON.",
	)
	parser.add_argument(
		"--output",
		type=Path,
		default=Path("data/raw/news_latest.jsonl"),
		help="JSONL output path.",
	)
	parser.add_argument(
		"--ticker",
		type=str,
		default=None,
		help="Default stock ticker stored in each record.",
	)
	parser.add_argument(
		"--max-articles",
		type=int,
		default=200,
		help="Max number of records to keep in this run.",
	)
	parser.add_argument(
		"--append",
		action="store_true",
		help="Append to output file instead of overwrite.",
	)
	return parser.parse_args()


def main() -> int:
	args = parse_args()
	source_configs = load_source_configs(args.config)
	scraper = NewsScraper(source_configs=source_configs, default_ticker=args.ticker)
	records, summary = scraper.run()

	if args.max_articles > 0:
		records = records[: args.max_articles]

	write_jsonl(records, args.output, append=args.append)

	overall = {
		"output": str(args.output),
		"records_written": len(records),
		"sources": summary,
	}
	print(json.dumps(overall, ensure_ascii=False, indent=2))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
