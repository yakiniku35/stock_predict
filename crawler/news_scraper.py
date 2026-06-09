import argparse
import copy
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote, urljoin

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
	rss_use_article_content: bool = False
	base_url: str | None = None
	article_link_include: list[str] | None = None
	article_link_exclude: list[str] | None = None
	ticker_keywords: list[str] | None = None
	request_headers: dict[str, str] | None = None
	content_extract_mode: str = "auto"
	content_extract_fallback: bool = True
	content_extract_timeout_seconds: int = 25


def now_utc_iso() -> str:
	return datetime.now(tz=timezone.utc).isoformat()


def compact_text(text: str) -> str:
	return " ".join((text or "").split())


def tag_text(tag: Any, name: str) -> str:
	node = tag.find(name)
	if not node:
		return ""
	return compact_text(node.get_text(" "))


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
	def __init__(
		self,
		source_configs: list[SourceConfig],
		default_ticker: str | None = None,
		min_content_length: int = 30,
	):
		self.source_configs = source_configs
		self.default_ticker = default_ticker
		self.min_content_length = max(1, min_content_length)
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

	def _normalize_extract_mode(self, mode: str | None) -> str:
		value = (mode or "auto").strip().lower()
		if value in {"r.jina.ai", "rjina", "r_jina_ai", "r-jina-ai"}:
			return "r.jina.ai"
		if value in {"markdown.new", "markdown_new", "markdown-new", "markdown"}:
			return "markdown.new"
		if value in {"html", "auto"}:
			return value
		return "auto"

	def _extract_text_from_markdown(self, markdown_text: str) -> tuple[str, str]:
		lines = [line.strip() for line in markdown_text.splitlines() if line.strip()]
		title = ""
		for line in lines:
			if line.startswith("#"):
				title = compact_text(line.lstrip("# "))
				break

		content = markdown_text
		content = re.sub(r"```.*?```", " ", content, flags=re.DOTALL)
		content = re.sub(r"!\[[^\]]*\]\([^\)]*\)", " ", content)
		content = re.sub(r"\[([^\]]+)\]\([^\)]*\)", r"\1", content)
		content = re.sub(r"[`*_>#\-]", " ", content)
		content = compact_text(content)
		return title, content

	def _extract_from_remote_markdown(self, article_url: str, source: SourceConfig) -> tuple[str, str] | None:
		mode = self._normalize_extract_mode(source.content_extract_mode)
		timeout_seconds = max(5, int(source.content_extract_timeout_seconds or source.timeout_seconds or 15))

		providers: list[str] = []
		if mode == "auto":
			providers = ["r.jina.ai", "markdown.new"]
		elif mode == "r.jina.ai":
			providers = ["r.jina.ai"]
		elif mode == "markdown.new":
			providers = ["markdown.new"]

		for provider in providers:
			if provider == "r.jina.ai":
				fetch_url = f"https://r.jina.ai/{article_url}"
			else:
				fetch_url = f"https://markdown.new/{article_url}"

			remote_text = self._fetch_text(fetch_url, timeout_seconds=timeout_seconds, retry_count=1)
			if not remote_text:
				continue
			title, content = self._extract_text_from_markdown(remote_text)
			if len(content) >= self.min_content_length:
				return title, content

		return None

	def _match_keywords(self, text: str, source: SourceConfig) -> bool:
		keywords = source.ticker_keywords or []
		if not keywords:
			return True
		lowered_text = text.lower()
		return any(keyword.lower() in lowered_text for keyword in keywords)

	def _is_meaningful_article(self, title: str, content: str) -> bool:
		if not title:
			return False
		if title.strip() in {"Yahoo股市", "Yahoo奇摩股市"}:
			return False
		return len(compact_text(content)) >= self.min_content_length

	def _is_allowed_link(self, url: str, source: SourceConfig) -> bool:
		includes = source.article_link_include or []
		excludes = source.article_link_exclude or []
		if includes and not any(re.search(pattern, url) for pattern in includes):
			return False
		if excludes and any(re.search(pattern, url) for pattern in excludes):
			return False
		return True

	def _extract_article_fields(self, article_html: str, source: SourceConfig) -> tuple[str, str | None, str]:
		article_soup = BeautifulSoup(article_html, "html.parser")
		title_node = article_soup.select_one(source.title_selector)
		time_node = article_soup.select_one(source.time_selector)
		content_nodes = article_soup.select(source.content_selector)

		title = compact_text(title_node.get_text(" ")) if title_node else ""
		if title in {"", "..."}:
			og_title = article_soup.select_one("meta[property='og:title']")
			if og_title:
				og_content = og_title.get("content")
				if isinstance(og_content, str):
					title = compact_text(og_content)
		if time_node:
			dt_attr = time_node.get("datetime")
			if isinstance(dt_attr, str):
				time_raw = compact_text(dt_attr)
			else:
				time_raw = compact_text(time_node.get_text(" "))
		else:
			time_raw = ""
		content = compact_text(" ".join(node.get_text(" ") for node in content_nodes))
		published_at = parse_datetime_or_none(time_raw)
		return title, published_at, content

	def _extract_article_from_url(self, article_url: str, source: SourceConfig) -> tuple[str, str | None, str]:
		mode = self._normalize_extract_mode(source.content_extract_mode)
		if mode != "html":
			remote_result = self._extract_from_remote_markdown(article_url, source)
			if remote_result:
				remote_title, remote_content = remote_result
				return remote_title, None, remote_content
			if not source.content_extract_fallback:
				return "", None, ""

		article_html = self._fetch_text(article_url, source.timeout_seconds, source.retry_count)
		if not article_html:
			return "", None, ""
		return self._extract_article_fields(article_html, source)

	def _scrape_rss(self, source: SourceConfig) -> tuple[list[NewsRecord], dict[str, int]]:
		stats = {"fetched": 0, "deduped": 0, "filtered": 0, "errors": 0}
		xml_text = self._fetch_text(source.list_url, source.timeout_seconds, source.retry_count)
		if not xml_text:
			stats["errors"] += 1
			return [], stats

		soup = BeautifulSoup(xml_text, "xml")
		items = soup.find_all("item")[: source.max_items]
		records: list[NewsRecord] = []

		for item in items:
			title = tag_text(item, "title")
			link = tag_text(item, "link")
			if not self._is_allowed_link(link, source):
				stats["filtered"] += 1
				continue
			pub_date = tag_text(item, "pubDate")
			raw_description = tag_text(item, "description")
			description = compact_text(BeautifulSoup(raw_description, "html.parser").get_text(" "))
			published_at = parse_datetime_or_none(pub_date)

			need_article_content = source.rss_use_article_content or self._normalize_extract_mode(source.content_extract_mode) != "html"
			if need_article_content:
				title_from_page, published_at_from_page, content_from_page = self._extract_article_from_url(link, source)
				if content_from_page:
					title = title_from_page or title
					published_at = published_at_from_page or published_at
					description = content_from_page or description
				else:
					stats["errors"] += 1

			full_text = compact_text(f"{title} {description}")
			if not self._is_meaningful_article(title, description):
				stats["filtered"] += 1
				continue
			if not self._match_keywords(full_text, source):
				stats["filtered"] += 1
				continue

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
			time.sleep(max(0.0, source.rate_limit_seconds))

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
			if not isinstance(href, str) or not href:
				continue
			links.append(urljoin(base_url, href))

		unique_links = list(dict.fromkeys(links))[: source.max_items]
		records: list[NewsRecord] = []

		for link in unique_links:
			if not self._is_allowed_link(link, source):
				stats["filtered"] += 1
				continue
			title, published_at, content = self._extract_article_from_url(link, source)
			if not content:
				stats["errors"] += 1
				continue

			full_text = compact_text(f"{title} {content}")
			if not self._is_meaningful_article(title, content):
				stats["filtered"] += 1
				continue

			if not self._match_keywords(full_text, source):
				stats["filtered"] += 1
				continue

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
				rss_use_article_content=bool(item.get("rss_use_article_content", False)),
				base_url=item.get("base_url"),
				article_link_include=item.get("article_link_include"),
				article_link_exclude=item.get("article_link_exclude"),
				ticker_keywords=item.get("ticker_keywords"),
				request_headers=item.get("request_headers"),
				content_extract_mode=item.get("content_extract_mode", "auto"),
				content_extract_fallback=bool(item.get("content_extract_fallback", True)),
				content_extract_timeout_seconds=int(item.get("content_extract_timeout_seconds", 25)),
			)
		)
	return [cfg for cfg in configs if cfg.list_url]


def write_jsonl(records: list[NewsRecord], output_path: Path, append: bool = False) -> None:
	output_path.parent.mkdir(parents=True, exist_ok=True)
	mode = "a" if append else "w"
	with output_path.open(mode, encoding="utf-8") as handle:
		for record in records:
			handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")


def write_summary(summary: dict[str, Any], output_path: Path) -> None:
	output_path.parent.mkdir(parents=True, exist_ok=True)
	output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_runtime_context(source_configs: list[SourceConfig], args: argparse.Namespace) -> list[SourceConfig]:
	context = {
		"ticker": args.ticker or "",
		"query": args.query or "",
		"query_encoded": quote(args.query or ""),
	}

	def fmt(value: str | None) -> str | None:
		if value is None:
			return None
		try:
			return value.format(**context)
		except KeyError:
			return value

	runtime_sources: list[SourceConfig] = []
	for source in source_configs:
		updated = copy.deepcopy(source)
		requires_ticker = any("{ticker}" in (val or "") for val in [source.name, source.list_url, source.base_url])
		requires_query = any(
			("{query}" in (val or "") or "{query_encoded}" in (val or ""))
			for val in [source.name, source.list_url, source.base_url]
		)
		if requires_ticker and not args.ticker:
			updated.enabled = False
		if requires_query and not args.query:
			updated.enabled = False

		updated.name = fmt(updated.name) or updated.name
		updated.list_url = fmt(updated.list_url) or updated.list_url
		updated.base_url = fmt(updated.base_url)
		if updated.ticker_keywords:
			updated.ticker_keywords = [fmt(keyword) or keyword for keyword in updated.ticker_keywords]
		if updated.article_link_include:
			updated.article_link_include = [fmt(pattern) or pattern for pattern in updated.article_link_include]
		if updated.article_link_exclude:
			updated.article_link_exclude = [fmt(pattern) or pattern for pattern in updated.article_link_exclude]

		if args.per_source_max_items > 0:
			updated.max_items = min(updated.max_items, args.per_source_max_items)

		if args.keyword and args.enforce_keyword_filter:
			extra_keywords = [kw.strip() for kw in args.keyword.split(",") if kw.strip()]
			if extra_keywords:
				updated.ticker_keywords = list(dict.fromkeys((updated.ticker_keywords or []) + extra_keywords))

		if args.content_extract_mode != "source":
			updated.content_extract_mode = args.content_extract_mode

		if args.disable_content_extract_fallback:
			updated.content_extract_fallback = False

		if args.content_extract_timeout > 0:
			updated.content_extract_timeout_seconds = args.content_extract_timeout

		runtime_sources.append(updated)

	return runtime_sources


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
		"--query",
		type=str,
		default="",
		help="Dynamic keyword used to format source URLs containing {query} or {query_encoded}.",
	)
	parser.add_argument(
		"--keyword",
		type=str,
		default="",
		help="Extra comma-separated keywords used when strict keyword filtering is enabled.",
	)
	parser.add_argument(
		"--enforce-keyword-filter",
		action="store_true",
		help="Force all sources to apply --keyword filters (higher precision, lower volume).",
	)
	parser.add_argument(
		"--max-articles",
		type=int,
		default=200,
		help="Max number of records to keep in this run.",
	)
	parser.add_argument(
		"--per-source-max-items",
		type=int,
		default=0,
		help="Optional cap per source to speed up runtime and rebalance source coverage.",
	)
	parser.add_argument(
		"--min-content-length",
		type=int,
		default=30,
		help="Minimum content length for keeping an article.",
	)
	parser.add_argument(
		"--append",
		action="store_true",
		help="Append to output file instead of overwrite.",
	)
	parser.add_argument(
		"--summary-output",
		type=Path,
		default=Path("data/raw/news_latest_summary.json"),
		help="Path to write run summary JSON.",
	)
	parser.add_argument(
		"--content-extract-mode",
		type=str,
		choices=["source", "auto", "html", "r.jina.ai", "markdown.new"],
		default="source",
		help="How to fetch article body. source=use config, auto=try r.jina.ai + markdown.new then HTML fallback.",
	)
	parser.add_argument(
		"--disable-content-extract-fallback",
		action="store_true",
		help="If remote extraction fails, do not fallback to source HTML selectors.",
	)
	parser.add_argument(
		"--content-extract-timeout",
		type=int,
		default=0,
		help="Override timeout (seconds) for r.jina.ai/markdown.new extraction. 0 means use source default.",
	)
	return parser.parse_args()


def main() -> int:
	args = parse_args()
	source_configs = load_source_configs(args.config)
	runtime_sources = apply_runtime_context(source_configs, args)
	scraper = NewsScraper(
		source_configs=runtime_sources,
		default_ticker=args.ticker,
		min_content_length=args.min_content_length,
	)
	records, summary = scraper.run()

	if args.max_articles > 0:
		records = records[: args.max_articles]

	write_jsonl(records, args.output, append=args.append)

	overall = {
		"output": str(args.output),
		"records_written": len(records),
		"runtime": {
			"ticker": args.ticker,
			"query": args.query,
			"keyword": args.keyword,
			"enforce_keyword_filter": args.enforce_keyword_filter,
			"max_articles": args.max_articles,
			"per_source_max_items": args.per_source_max_items,
			"min_content_length": args.min_content_length,
			"content_extract_mode": args.content_extract_mode,
			"disable_content_extract_fallback": args.disable_content_extract_fallback,
			"content_extract_timeout": args.content_extract_timeout,
		},
		"sources": summary,
	}
	write_summary(overall, args.summary_output)
	print(json.dumps(overall, ensure_ascii=False, indent=2))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
