#!/usr/bin/env python3
"""Self-check for the xufeng-promo static site (standard library only)."""

from __future__ import annotations

import hashlib
import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
HTML_FILES = ("index.html", "guide.html")
EXPLAINER_FILE = "invoice-explainer.html"
MANUAL_FILE = "manual.html"
MESSAGE_FILE = "message.html"
# 经销商海报：导出成 PNG 后会脱离仓库单独流传，价格写错追不回来，
# 所以事实必须与 pricing.json 对齐；但不套用页面级的文案格式要求（版面有限）。
POSTER_FILE = "dealer-poster.html"
NAV_PAGE_FILES = (*HTML_FILES, EXPLAINER_FILE, MANUAL_FILE, MESSAGE_FILE)
EXPLAINER_ASSETS = ("assets/explainer.css", "assets/explainer.js")
FACTS_FILE = "facts.json"
EXPLAINER_PAGE_FORBIDDEN_TERMS = ("RPA", "乐企")
MANUAL_PAGE_FORBIDDEN_TERMS = ("RPA", "乐企", "试用期")
# 商户手册里不得出现上游接口返回码。这几串数字对商户没有任何可操作含义，只会被
# 照着念给客服；码本身留在服务端日志、数据库和运营卡片里，排障不受影响。
# 2026-09-11 反转：此前这三个码是「必须存在」，导致任何去技术码的改动都会被自家
# 验收脚本挡回来。
MANUAL_FORBIDDEN_ERROR_CODES = ("8047", "3001", "8011")
# 手册必须给出人工兜底入口：注册页的工单。没有在线客服，只有工单系统。
MANUAL_TICKET_MARKERS = ("提交工单",)
# 全站不得出现「在线客服」：人工处理后在注册页回复，不是即时对话，这么写会让商户等回复。
SITE_FORBIDDEN_SUPPORT_TERMS = ("在线客服",)
# 宣传站对外一律称「开票平台」，正文不出现上游厂商名。注册页的品牌名是另一回事
# （那是待定的业务决定），这条只管宣传站这几页。
SITE_FORBIDDEN_VENDOR_TERMS = ("票通",)
# 例外只有这两个正式名称：对外平台名，以及商户在登录页上看到的标题原文。
SITE_ALLOWED_VENDOR_NAMES = ("旭峰微票通开票平台", "票通电子发票服务平台")


# 含「票通」但属于普通中文的固定用语，先整体换掉再数厂商名。只列确认过的词：
# 不能笼统豁免「前一个字是发/开」——「请转发票通平台公告」的「发」来自「转发」，
# 那里的「票通」就是厂商名；也不能只看后一个字——那样「旭峰微票通过开票平台」这种
# 写错的名称会被放过（Codex 两轮复核复现）。
VENDOR_ORDINARY_PHRASES = (
    "发票通常",
    "发票通用",
    "发票通行",
    "发票通知",
    "发票通过",
    "发票通道",
    "开票通常",
    "开票通知",
    "开票通过",
    "开票通道",
)
# 守卫自检用例：(文案, 应计入的厂商名次数)。每次运行都跑，规则改坏了立刻知道。
VENDOR_GUARD_CASES = (
    ("旭峰微票通开票平台", 0),
    ("票通电子发票服务平台", 0),
    ("发票通常三分钟到账", 0),
    ("电子发票通用指南", 0),
    ("发票通行规则", 0),
    ("开票通道正常", 0),
    ("旭峰微票通过开票平台", 1),
    ("票通知电子发票服务平台", 1),
    ("票通道歉", 1),
    ("票通平台", 1),
    ("请转发票通平台公告", 1),
)


def without_allowed_vendor_names(source: str) -> str:
    """把两个正式名称换成占位符再数厂商名，其余任何「票通」照样拦。

    换成占位符而不是删掉：删掉会让前后文字拼接出新的裸「票通」，或把真违规藏进拼接里。
    """
    for name in SITE_ALLOWED_VENDOR_NAMES:
        source = source.replace(name, "\u2063")
    return source


def count_vendor_mentions(source: str) -> int:
    text = without_allowed_vendor_names(source)
    for phrase in VENDOR_ORDINARY_PHRASES:
        text = text.replace(phrase, "\u2063")
    return text.count("票通")


class VisibleTextParser(HTMLParser):
    """浏览器里真正显示出来的文字：跳过注释与 script/style，实体自动解码。

    不用正则去标签：注释里带「>」时正则会提前截断，留下的碎字把禁词隔开从而漏放；
    而 script/style/注释里的内容又会被拼进来造成误报（Codex 第二轮复核复现）。
    行内片段直接相连不加空格，「在线<strong>客服</strong>」才能还原成「在线客服」。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skip_depth += 1
            return
        # 这几个属性商户同样看得见：悬停提示、图片替代文字、输入框占位、读屏文字。
        # 单独成段（前后加换行），不和相邻正文拼接。
        for name, value in attrs:
            if value and name in {"title", "alt", "placeholder", "aria-label"}:
                self.parts.append(f"\n{value}\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def visible_text(source: str) -> str:
    parser = VisibleTextParser()
    parser.feed(source)
    parser.close()
    return "".join(parser.parts)

MANUAL_PDF_MIN_BYTES = 400_000
MANUAL_DURATION_RANGES = ("1~5 分钟", "5~10 分钟")
MANUAL_SOURCE_ATTRIBUTION = "美菜官方手册 v1.1 整理"
REQUIRED_FILES = (
    *HTML_FILES,
    EXPLAINER_FILE,
    MANUAL_FILE,
    "assets/style.css",
    *EXPLAINER_ASSETS,
    FACTS_FILE,
    "check.py",
    "README.md",
)
# 指南必须引用的步骤截图（均为真实截图）。step-05/06 已退役：免费期不经过
# 收银台，对应步骤改为文字说明卡。
PLACEHOLDER_IMAGES = {
    f"assets/screenshots/step-{number:02d}.png" for number in range(1, 5)
}
FORBIDDEN_TERMS = (
    "待审核人补充",
    "\u5305\u8fc7",
    "\u7edd\u5bf9",
    "\u767e\u5206\u767e",
    "\u6700\u4f4e\u4ef7",
    "\u7a33\u8d5a",
    "\u514d\u7a0e",
    "\u5b98\u65b9\u6307\u5b9a",
    "\u8bd5\u7528\u671f",
)
FAQ_QUESTIONS = (
    "这是什么服务？我为什么需要它？",
    "多少钱？怎么收费？",
    "什么情况可以退款？怎么申请？",
    "开通需要多长时间？",
    "我需要准备什么材料？",
    "我是小规模纳税人，有什么税率优惠？",
    "营业执照/发票信息填错了或变更了怎么办？",
    "到期了怎么续费？续费多少钱？",
    "开通后客户的发票多久能开出来？",
    "有问题找谁？",
)


def normalized(text: str) -> str:
    """Collapse whitespace so checks are not coupled to source formatting."""
    return re.sub(r"\s+", " ", text).strip()


def is_external_reference(value: str) -> bool:
    parsed = urlsplit(value)
    return bool(parsed.scheme or parsed.netloc or value.startswith("//"))


class SiteHTMLParser(HTMLParser):
    """Collect only the document facts needed by this verifier."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.metas: list[dict[str, str]] = []
        self.images: list[dict[str, str]] = []
        self.links: list[dict[str, object]] = []
        self.asset_refs: list[tuple[str, str, str]] = []
        self.figures: list[dict[str, object]] = []
        self._open_links: list[dict[str, object]] = []
        self._figure: dict[str, object] | None = None
        self._caption_depth = 0

    def handle_starttag(
        self, tag: str, attrs_list: list[tuple[str, str | None]]
    ) -> None:
        attrs = {key: value or "" for key, value in attrs_list}

        if tag == "meta":
            self.metas.append(attrs)
        elif tag == "img":
            self.images.append(attrs)
            if self._figure is not None:
                figure_images = self._figure["images"]
                assert isinstance(figure_images, list)
                figure_images.append(attrs)
        elif tag == "a":
            link: dict[str, object] = {"attrs": attrs, "text": []}
            self._open_links.append(link)
        elif tag == "figure":
            self._figure = {"images": [], "caption": []}
        elif tag == "figcaption" and self._figure is not None:
            self._caption_depth += 1

        for attr_name in ("src", "href"):
            value = attrs.get(attr_name)
            if value and tag in {"img", "script", "link"}:
                self.asset_refs.append((tag, attr_name, value))

    def handle_startendtag(
        self, tag: str, attrs_list: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs_list)

    def handle_data(self, data: str) -> None:
        self.text_parts.append(data)
        for link in self._open_links:
            link_text = link["text"]
            assert isinstance(link_text, list)
            link_text.append(data)
        if self._figure is not None and self._caption_depth:
            caption = self._figure["caption"]
            assert isinstance(caption, list)
            caption.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._open_links:
            self.links.append(self._open_links.pop())
        elif tag == "figcaption" and self._caption_depth:
            self._caption_depth -= 1
        elif tag == "figure" and self._figure is not None:
            self.figures.append(self._figure)
            self._figure = None

    @property
    def text(self) -> str:
        return normalized(" ".join(self.text_parts))


class Checks:
    def __init__(self) -> None:
        self.passed: list[tuple[str, str]] = []
        self.failed: list[tuple[str, str]] = []

    def record(self, label: str, problems: list[str], success: str) -> None:
        if problems:
            self.failed.append((label, "; ".join(problems)))
        else:
            self.passed.append((label, success))

    def emit(self) -> int:
        print("xufeng-promo self-check")
        for label, detail in self.passed:
            print(f"[PASS] {label}: {detail}")
        for label, detail in self.failed:
            print(f"[FAIL] {label}: {detail}")
        total = len(self.passed) + len(self.failed)
        if self.failed:
            print(f"RESULT: FAIL ({len(self.failed)} of {total} check groups failed)")
            return 1
        print(f"RESULT: PASS ({total} check groups)")
        return 0


def load_sources(checks: Checks) -> tuple[dict[str, object], dict[str, str], dict[str, SiteHTMLParser]]:
    file_problems = [name for name in REQUIRED_FILES if not (ROOT / name).is_file()]
    checks.record(
        "Required deliverables",
        [f"missing {name}" for name in file_problems],
        ", ".join(REQUIRED_FILES),
    )

    pricing_path = ROOT / "pricing.json"
    try:
        pricing = json.loads(pricing_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        checks.record("Pricing source", [f"cannot read pricing.json ({exc})"], "")
        return {}, {}, {}

    pricing_problems: list[str] = []
    expected_types = {
        "currency": str,
        "first_year_price": int,
        "renewal_price": int,
        "unit": str,
        "promo_start": str,
        "promo_end": str,
        "renewal_deadline": str,
        "two_year_price": int,
        "promo_slogan": str,
        "promo_policy": str,
        "refund_slogan": str,
        "refund_policy": str,
        "refund_channel": str,
        "service_entity": str,
        "entry_hint": str,
    }
    for key, expected_type in expected_types.items():
        if key not in pricing:
            pricing_problems.append(f"missing key {key}")
        elif not isinstance(pricing[key], expected_type):
            pricing_problems.append(f"{key} must be {expected_type.__name__}")
    checks.record(
        "Pricing source",
        pricing_problems,
        "required fields and types are valid",
    )

    sources: dict[str, str] = {}
    parsers: dict[str, SiteHTMLParser] = {}
    for name in HTML_FILES:
        path = ROOT / name
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        parser = SiteHTMLParser()
        parser.feed(source)
        parser.close()
        sources[name] = source
        parsers[name] = parser
    return pricing, sources, parsers


def check_pricing(
    checks: Checks,
    pricing: dict[str, object],
    sources: dict[str, str],
    parsers: dict[str, SiteHTMLParser],
) -> None:
    required_keys = {
        "first_year_price",
        "renewal_price",
        "unit",
        "promo_slogan",
        "promo_policy",
        "refund_slogan",
        "refund_policy",
        "refund_channel",
        "service_entity",
    }
    if not required_keys.issubset(pricing):
        checks.record("Pricing and legal facts", ["pricing source is incomplete"], "")
        return

    first = int(pricing["first_year_price"])
    renewal = int(pricing["renewal_price"])
    unit = str(pricing["unit"])
    promo_slogan = str(pricing["promo_slogan"])
    promo_policy = str(pricing["promo_policy"])
    two_year = str(pricing.get("two_year_price", ""))
    renewal_deadline = str(pricing.get("renewal_deadline", ""))
    refund_slogan = str(pricing["refund_slogan"])
    refund = str(pricing["refund_policy"])
    refund_channel = str(pricing["refund_channel"])
    entity = str(pricing["service_entity"])
    allowed_prices = {first, renewal, int(pricing.get("two_year_price", 0))}
    problems: list[str] = []

    for name in HTML_FILES:
        source = sources.get(name)
        parser = parsers.get(name)
        if source is None or parser is None:
            problems.append(f"{name} unavailable")
            continue
        text = parser.text

        for value, key in (
            (first, "first_year_price"),
            (renewal, "renewal_price"),
        ):
            expected = re.compile(
                rf'data-price-key=["\']{re.escape(key)}["\'][^>]*>\s*{value}\s*<',
                re.IGNORECASE,
            )
            if not expected.search(source):
                problems.append(f"{name} lacks verified {key}={value}")
            price_with_unit = re.compile(
                rf"(?<!\d){value}(?!\d)\s+{re.escape(unit)}"
            )
            if not price_with_unit.search(text):
                problems.append(f"{name} lacks '{value} {unit}'")

        for match in re.finditer(r"(?<!\d)(\d[\d,]*)\s*元", text):
            amount = int(match.group(1).replace(",", ""))
            if amount not in allowed_prices:
                problems.append(f"{name} has unknown yuan amount {amount}")

        for match in re.finditer(r"¥\s*(\d[\d,]*)", text):
            amount = int(match.group(1).replace(",", ""))
            if amount not in allowed_prices:
                problems.append(f"{name} has unknown ¥ amount {amount}")

        # 每档价格绑定自己的计价单位：年费按年，两年套餐按税号一次性。
        unit_by_price = {first: unit, renewal: unit}
        if pricing.get("two_year_price"):
            unit_by_price[int(pricing["two_year_price"])] = "元/税号"
        for amount, amount_unit in unit_by_price.items():
            for match in re.finditer(rf"(?<!\d){amount}(?!\d)", text):
                context = text[match.start() : match.end() + len(amount_unit) + 2]
                if not re.match(rf"{amount}\s+{re.escape(amount_unit)}", context):
                    problems.append(
                        f"{name} uses {amount} outside the exact '{amount_unit}' price context"
                    )

        if promo_slogan not in text:
            problems.append(f"{name} promo slogan differs from pricing.json")
        if two_year and f"{two_year} 元/税号" not in text:
            problems.append(f"{name} lacks the two-year bundle price {two_year} 元/税号")
        if renewal_deadline and renewal_deadline.replace("-", "-") not in text:
            problems.append(f"{name} lacks the renewal deadline {renewal_deadline}")
        if promo_policy not in text:
            problems.append(f"{name} promo policy differs from pricing.json")
        if refund_slogan not in text:
            problems.append(f"{name} refund slogan differs from pricing.json")
        if refund not in text:
            problems.append(f"{name} refund policy differs from pricing.json")
        if refund_channel not in text:
            problems.append(f"{name} refund channel differs from pricing.json")
        if entity not in text:
            problems.append(f"{name} service entity differs from pricing.json")

    checks.record(
        "Pricing and legal facts",
        problems,
        f"{first}/{renewal} {unit}, refund slogan/policy/channel, and service entity match pricing.json",
    )


def check_copy(
    checks: Checks, sources: dict[str, str], parsers: dict[str, SiteHTMLParser]
) -> None:
    problems: list[str] = []
    for name in HTML_FILES:
        source = sources.get(name, "")
        for term in FORBIDDEN_TERMS:
            if term in source:
                problems.append(f"{name} contains forbidden term {term!r}")
    # 厂商名单独扫全部对外页面（含手册与留言页），而不只是 HTML_FILES 那两页。
    for wording, expected in VENDOR_GUARD_CASES:
        if count_vendor_mentions(wording) != expected:
            problems.append(
                f"vendor-name guard self-test failed on {wording!r}: "
                f"counted {count_vendor_mentions(wording)}, expected {expected}"
            )
    # 海报也要扫：它会导出成 PNG 脱离仓库流传，写错了追不回来。
    for name in (*NAV_PAGE_FILES, POSTER_FILE):
        source = sources.get(name, "") or (ROOT / name).read_text(encoding="utf-8")
        for term in SITE_FORBIDDEN_VENDOR_TERMS:
            occurrences = count_vendor_mentions(source)
            if occurrences:
                problems.append(
                    f"{name} names the upstream vendor {term!r} {occurrences} time(s); "
                    f"say 开票平台 instead"
                )
        for term in SITE_FORBIDDEN_SUPPORT_TERMS:
            # 查商户实际看得到的：正文（防行内标签、实体绕过）与 title/alt/placeholder/
            # aria-label 属性。注释、script、style 里的开发说明不算对客文案，不查。
            occurrences = visible_text(source).count(term)
            if occurrences:
                problems.append(
                    f"{name} says {term!r} {occurrences} time(s); there is no live support, "
                    f"only the ticket on the register page (say 提交工单)"
                )
        if re.search(r"15\s*天\s*退\s*款", source):
            problems.append(f"{name} contains an unsupported 15-day refund promise")
        if "\u65e0\u7406\u7531\u9000\u6b3e" in source:
            problems.append(f"{name} contains an unsupported no-reason refund promise")

    index_text = parsers.get("index.html", SiteHTMLParser()).text
    for question in FAQ_QUESTIONS:
        if question not in index_text:
            problems.append(f"index.html missing FAQ question {question!r}")
    policy_statement = "小规模纳税人可依国家现行政策享受 3% 减按 1% 征收"
    if policy_statement not in index_text:
        problems.append("index.html missing policy-qualified small-taxpayer wording")
    if "这不是本服务对税负结果的承诺" not in index_text:
        problems.append("index.html missing non-promise tax disclaimer")

    checks.record(
        "Copy and FAQ",
        problems,
        "forbidden-term scan clean; all 10 fixed FAQs and tax-policy disclaimer present",
    )


def check_images(
    checks: Checks, parsers: dict[str, SiteHTMLParser]
) -> None:
    problems: list[str] = []
    used_placeholders: set[str] = set()

    for name, parser in parsers.items():
        for image in parser.images:
            src = image.get("src", "")
            alt = normalized(image.get("alt", ""))
            if not src:
                problems.append(f"{name} has img without src")
                continue
            pure_path = PurePosixPath(src)
            if (
                is_external_reference(src)
                or not pure_path.parts
                or pure_path.parts[0] != "assets"
                or ".." in pure_path.parts
            ):
                problems.append(f"{name} img src is not a safe assets/ path: {src}")
            elif not (ROOT / src).is_file() and src not in PLACEHOLDER_IMAGES:
                problems.append(f"{name} img is missing and not declared: {src}")
            if src in PLACEHOLDER_IMAGES:
                used_placeholders.add(src)
            if not alt:
                problems.append(f"{name} img lacks non-empty alt text: {src}")

        for figure in parser.figures:
            images = figure["images"]
            caption = normalized(" ".join(figure["caption"]))
            assert isinstance(images, list)
            if images and not caption:
                problems.append(f"{name} has screenshot figure without caption")

    guide_sources = {
        image.get("src", "")
        for image in parsers.get("guide.html", SiteHTMLParser()).images
    }
    missing_from_guide = sorted(PLACEHOLDER_IMAGES - guide_sources)
    if missing_from_guide:
        problems.append(
            "guide.html does not reference " + ", ".join(missing_from_guide)
        )
    missing_anywhere = sorted(PLACEHOLDER_IMAGES - used_placeholders)
    if missing_anywhere:
        problems.append("unused declared placeholders: " + ", ".join(missing_anywhere))

    checks.record(
        "Screenshot placeholders",
        problems,
        "step-01 to step-04 real screenshots use safe paths, alt text, and captions",
    )


def check_ctas_and_assets(
    checks: Checks, parsers: dict[str, SiteHTMLParser]
) -> None:
    problems: list[str] = []

    for name, parser in parsers.items():
        app_cta_count = 0
        for link in parser.links:
            attrs = link["attrs"]
            text_parts = link["text"]
            assert isinstance(attrs, dict)
            assert isinstance(text_parts, list)
            href = str(attrs.get("href", ""))
            text = normalized(" ".join(text_parts))

            if not href:
                problems.append(f"{name} has anchor without href ({text!r})")
            elif is_external_reference(href):
                problems.append(f"{name} has external/direct link {href}")
            elif re.search(r"(register|signup|registration|\u6ce8\u518c)", href, re.I):
                problems.append(f"{name} has registration-like link {href}")

            if "data-cta" in attrs:
                app_cta_count += 1
                if not href.startswith("#"):
                    problems.append(f"{name} CTA must use an in-page target: {href}")
                if "美菜卖家后台" not in text:
                    problems.append(
                        f"{name} CTA copy must direct users to 美菜卖家后台 ({text!r})"
                    )
        if app_cta_count == 0:
            problems.append(f"{name} has no checked Meicai App CTA")

        for tag, attr, value in parser.asset_refs:
            if is_external_reference(value):
                problems.append(f"{name} loads external {tag} {attr}: {value}")

    css = (ROOT / "assets/style.css").read_text(encoding="utf-8")
    if re.search(r"@import\b|url\(\s*['\"]?(?:https?:)?//", css, re.I):
        problems.append("assets/style.css imports an external resource")

    checks.record(
        "CTA and local assets",
        problems,
        "CTAs point only to in-page anchors and direct users back to 美菜卖家后台; no external assets",
    )


def check_responsive_contract(
    checks: Checks, sources: dict[str, str], parsers: dict[str, SiteHTMLParser]
) -> None:
    problems: list[str] = []
    for name, parser in parsers.items():
        viewports = [
            meta.get("content", "")
            for meta in parser.metas
            if meta.get("name", "").lower() == "viewport"
        ]
        if not any(
            "width=device-width" in value.replace(" ", "").lower()
            and "initial-scale=1" in value.replace(" ", "").lower()
            for value in viewports
        ):
            problems.append(f"{name} lacks the required mobile viewport meta")
        if "<!doctype html>" not in sources[name].lower():
            problems.append(f"{name} lacks HTML5 doctype")
        if not re.search(r'<html\b[^>]*\blang=["\']zh-CN["\']', sources[name], re.I):
            problems.append(f"{name} lacks lang=zh-CN")

    css = (ROOT / "assets/style.css").read_text(encoding="utf-8")
    css_flat = normalized(css)
    required_css_patterns = {
        "global border-box": r"\*\s*,.*box-sizing:\s*border-box",
        "horizontal overflow guard": r"overflow-x:\s*(?:clip|hidden)",
        "responsive media rule": r"@media\s*\(\s*min-width:",
        "responsive images": r"img\s*,\s*svg\s*\{[^}]*max-width:\s*100%",
        "CSS color variables": r":root\s*\{[^}]*--brand:",
    }
    for label, pattern in required_css_patterns.items():
        if not re.search(pattern, css_flat, re.I):
            problems.append(f"assets/style.css lacks {label}")
    if re.search(r"\b100vw\b", css):
        problems.append("assets/style.css uses 100vw, a common mobile overflow source")

    checks.record(
        "Mobile responsive safeguards",
        problems,
        "viewport meta, border-box, overflow guard, responsive media/images, and CSS variables present",
    )


def check_static_stack(checks: Checks, sources: dict[str, str]) -> None:
    problems: list[str] = []
    combined = "\n".join(sources.values())
    if re.search(r"<script\b", combined, re.I):
        problems.append("HTML contains a script tag")
    if re.search(
        r"\b(?:react|react-dom|vue|angular|bootstrap|tailwind)(?:\.min)?\.(?:js|css)\b",
        combined,
        re.I,
    ):
        problems.append("HTML references a framework asset")
    if re.search(r"@font-face\b", (ROOT / "assets/style.css").read_text(encoding="utf-8"), re.I):
        problems.append("CSS embeds a web font")
    checks.record(
        "Zero-framework stack",
        problems,
        "plain HTML/CSS with no scripts, framework assets, CDN, or web fonts",
    )


def check_message_form(checks: Checks) -> None:
    problems: list[str] = []
    try:
        source = (ROOT / MESSAGE_FILE).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        checks.record("message form", [f"cannot read {MESSAGE_FILE} ({exc})"], "")
        return

    script = ROOT / "assets" / "message.js"
    if not script.is_file():
        problems.append("assets/message.js is missing")
        script_source = ""
    else:
        script_source = script.read_text(encoding="utf-8")

    # 税号与邮箱必填是产品硬要求，前后端都不能悄悄放松。
    for field_id in ('id="inquiryTaxpayer"', 'id="inquiryEmail"', 'id="inquiryContent"'):
        if field_id not in source:
            problems.append(f"{MESSAGE_FILE} lacks field {field_id}")
            continue
        # 只看这一个标签自身（到最近的 '>' 为止），否则会把下一个字段的
        # required 误算进来，形成永远通过的假断言。
        tag = source.split(field_id, 1)[1].split(">", 1)[0]
        if "required" not in tag:
            problems.append(f"{MESSAGE_FILE} field {field_id} is not marked required")

    if source.count("必填") < 3:
        problems.append(f"{MESSAGE_FILE} does not label taxpayer/email/content as 必填")
    if 'id="inquiryCaptcha"' not in source:
        problems.append(f"{MESSAGE_FILE} lacks the captcha field that keeps bots out")

    style = (ROOT / "assets" / "style.css").read_text(encoding="utf-8")
    if 'class="' in source and "hidden" in source and not re.search(r"\.hidden\s*\{", style):
        problems.append("assets/style.css lacks a .hidden rule, so hidden panels stay visible")

    if "https://fapiao.chinavtax.com" not in script_source:
        problems.append("assets/message.js does not post to the production API over https")
    if "/api/public/inquiries" not in script_source:
        problems.append("assets/message.js does not call the public inquiry endpoint")
    if re.search(r"https?://(?!fapiao\.chinavtax\.com)[\w.-]+", script_source):
        problems.append("assets/message.js references an unexpected external host")

    for name in (MESSAGE_FILE,):
        page = source
        if re.search(r"<script\b[^>]*\bsrc=[\"'](?!assets/)", page):
            problems.append(f"{name} loads a script from outside assets/")

    checks.record(
        "message form",
        problems,
        "taxpayer/email/content are required, captcha is present, and the form posts only to the production inquiry API",
    )


def check_dealer_poster(checks: Checks, pricing: dict) -> None:
    """经销商海报的事实一致性：金额、免费期截止日、服务主体都以 pricing.json 为准。"""
    problems: list[str] = []
    try:
        source = (ROOT / POSTER_FILE).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        checks.record("dealer poster facts", [f"cannot read {POSTER_FILE} ({exc})"], "")
        return

    parser = SiteHTMLParser()
    parser.feed(source)
    parser.close()
    text = parser.text

    allowed_prices = {
        int(pricing["first_year_price"]),
        int(pricing["renewal_price"]),
        int(pricing.get("two_year_price", 0)),
    }
    for pattern in (r"(?<!\d)(\d[\d,]*)\s*元", r"¥\s*(\d[\d,]*)"):
        for match in re.finditer(pattern, text):
            amount = int(match.group(1).replace(",", ""))
            if amount not in allowed_prices:
                problems.append(f"{POSTER_FILE} has unknown amount {amount}")

    promo_end = str(pricing.get("promo_end", ""))
    if promo_end:
        year, month, day = promo_end.split("-")
        spelled = f"{year} 年 {int(month)} 月 {int(day)} 日"
        if promo_end not in text and spelled not in text:
            problems.append(f"{POSTER_FILE} lacks promo_end {promo_end}")

    entity = str(pricing.get("service_entity", ""))
    if entity and entity not in text:
        problems.append(f"{POSTER_FILE} lacks service entity {entity}")

    checks.record(
        "dealer poster facts",
        problems,
        "poster amounts, promo deadline, and service entity all match pricing.json",
    )


def check_readme(checks: Checks) -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    problems: list[str] = []
    for required in (
        "python3 -m http.server 8900",
        "python3 check.py",
        "Zeabur",
        "assets/screenshots/",
    ):
        if required not in readme:
            problems.append(f"README.md missing {required!r}")
    checks.record(
        "README instructions",
        problems,
        "project summary, local preview, self-check, deployment, and screenshot handoff documented",
    )


def load_explainer_facts(checks: Checks) -> dict[str, object]:
    facts_path = ROOT / FACTS_FILE
    try:
        facts = json.loads(facts_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        checks.record(
            "Explainer — fact source",
            [f"cannot read {FACTS_FILE} ({exc})"],
            "",
        )
        return {}

    problems: list[str] = []
    # facts.json 只服务 check.py，不进镜像：里面有页面禁用词名单和通道实现，
    # 曾被 Dockerfile 的 COPY . 一起发布成公开的 /facts.json。.dockerignore 少
    # 掉这一行就会悄悄漏回去，所以在这里盯住。
    dockerignore = ROOT / ".dockerignore"
    ignored = (
        dockerignore.read_text(encoding="utf-8").splitlines()
        if dockerignore.is_file()
        else []
    )
    if FACTS_FILE not in {
        line.strip() for line in ignored if not line.lstrip().startswith("#")
    }:
        problems.append(
            f".dockerignore must exclude {FACTS_FILE} so it is not published"
        )

    object_fields = {
        "risk_auth": {
            "name": str,
            "cycle": str,
            "cycle_days": int,
            "where": str,
            "method": str,
            "note": str,
        },
        "sms_auth": {
            "name": str,
            "cycle": str,
            "cycle_hours": int,
            "method": str,
            "note": str,
        },
        "channel_mode": {
            "name": str,
            "desc": str,
            "why_auth": str,
        },
        "channels_reserved": {
            "primary_future": str,
            "fallback": str,
            "merchant_view": str,
        },
    }
    for object_name, required_fields in object_fields.items():
        value = facts.get(object_name)
        if not isinstance(value, dict):
            problems.append(f"{object_name} must be an object")
            continue
        for field_name, expected_type in required_fields.items():
            field_value = value.get(field_name)
            if not isinstance(field_value, expected_type) or (
                expected_type is str and not field_value.strip()
            ):
                problems.append(
                    f"{object_name}.{field_name} must be a non-empty "
                    f"{expected_type.__name__}"
                )

    for key in (
        "auth_failure_recovery",
        "channels_reserved_note",
        "compliance_note",
    ):
        value = facts.get(key)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"{key} must be a non-empty string")

    page_terminology = facts.get("page_terminology")
    if not isinstance(page_terminology, dict):
        problems.append("page_terminology must be an object")
    else:
        must_use = page_terminology.get("must_use")
        forbidden_on_page = page_terminology.get("forbidden_on_page")
        if not isinstance(must_use, str) or not must_use.strip():
            problems.append("page_terminology.must_use must be a non-empty string")
        if (
            not isinstance(forbidden_on_page, list)
            or not forbidden_on_page
            or not all(
                isinstance(item, str) and item.strip()
                for item in forbidden_on_page
            )
        ):
            problems.append(
                "page_terminology.forbidden_on_page must contain non-empty strings"
            )
        elif not set(EXPLAINER_PAGE_FORBIDDEN_TERMS).issubset(forbidden_on_page):
            problems.append(
                "page_terminology.forbidden_on_page must include the two fixed "
                "explainer terminology bans"
            )

    invoice_flow = facts.get("invoice_flow")
    if (
        not isinstance(invoice_flow, list)
        or len(invoice_flow) != 4
        or not all(isinstance(item, str) and item.strip() for item in invoice_flow)
    ):
        problems.append("invoice_flow must contain exactly 4 non-empty strings")

    knowledge = facts.get("shudian_knowledge")
    if not isinstance(knowledge, list) or len(knowledge) != 5:
        problems.append("shudian_knowledge must contain exactly 5 items")
    else:
        for index, item in enumerate(knowledge):
            if not isinstance(item, dict):
                problems.append(f"shudian_knowledge[{index}] must be an object")
                continue
            for key in ("q", "a"):
                value = item.get(key)
                if not isinstance(value, str) or not value.strip():
                    problems.append(
                        f"shudian_knowledge[{index}].{key} must be a non-empty string"
                    )

    risk_auth = facts.get("risk_auth")
    if isinstance(risk_auth, dict):
        cycle = risk_auth.get("cycle")
        cycle_days = risk_auth.get("cycle_days")
        if (
            isinstance(cycle, str)
            and isinstance(cycle_days, int)
            and f"{cycle_days} 天" not in cycle
        ):
            problems.append("risk_auth.cycle disagrees with risk_auth.cycle_days")

    sms_auth = facts.get("sms_auth")
    if isinstance(sms_auth, dict):
        cycle = sms_auth.get("cycle")
        cycle_hours = sms_auth.get("cycle_hours")
        if (
            isinstance(cycle, str)
            and isinstance(cycle_hours, int)
            and f"{cycle_hours} 小时" not in cycle
        ):
            problems.append("sms_auth.cycle disagrees with sms_auth.cycle_hours")

    channel_mode = facts.get("channel_mode")
    if isinstance(channel_mode, dict) and isinstance(page_terminology, dict):
        if channel_mode.get("name") != page_terminology.get("must_use"):
            problems.append(
                "channel_mode.name disagrees with page_terminology.must_use"
            )

    checks.record(
        "Explainer — fact source",
        problems,
        "facts.json parses and stays out of the published image; authentication, account-mode terminology, reserved channels, flow, knowledge, and compliance fields are valid",
    )
    return facts if not problems else {}


def explainer_fact_strings(facts: dict[str, object]) -> list[str]:
    strings: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)

    for key in (
        "risk_auth",
        "sms_auth",
        "auth_failure_recovery",
        "channel_mode",
        "invoice_flow",
        "shudian_knowledge",
        "compliance_note",
    ):
        collect(facts.get(key))
    return strings


def check_explainer(
    checks: Checks,
    sources: dict[str, str],
    parsers: dict[str, SiteHTMLParser],
) -> None:
    facts = load_explainer_facts(checks)
    explainer_path = ROOT / EXPLAINER_FILE
    explainer_source = ""
    explainer_parser = SiteHTMLParser()
    if explainer_path.is_file():
        try:
            explainer_source = explainer_path.read_text(encoding="utf-8")
            explainer_parser.feed(explainer_source)
            explainer_parser.close()
        except (OSError, UnicodeError) as exc:
            explainer_source = ""
            explainer_parser = SiteHTMLParser()
            explainer_read_problem = f"cannot read {EXPLAINER_FILE} ({exc})"
        else:
            explainer_read_problem = ""
    else:
        explainer_read_problem = f"missing {EXPLAINER_FILE}"

    fact_problems: list[str] = []
    if not facts:
        fact_problems.append("facts.json is unavailable or incomplete")
    if explainer_read_problem:
        fact_problems.append(explainer_read_problem)
    if facts and explainer_source:
        explainer_text = explainer_parser.text
        for value in explainer_fact_strings(facts):
            if normalized(value) not in explainer_text:
                fact_problems.append(
                    f"{EXPLAINER_FILE} lacks facts.json text {value!r}"
                )

        risk_auth = facts["risk_auth"]
        sms_auth = facts["sms_auth"]
        assert isinstance(risk_auth, dict)
        assert isinstance(sms_auth, dict)
        cycle_days = int(risk_auth["cycle_days"])
        cycle_hours = int(sms_auth["cycle_hours"])
        numeric_bindings = (
            ("risk_auth.cycle_days", cycle_days),
            ("sms_auth.cycle_hours", cycle_hours),
        )
        for fact_key, value in numeric_bindings:
            pattern = re.compile(
                rf'data-fact-key=["\']{re.escape(fact_key)}["\'][^>]*>'
                rf"\s*{value}\s*<",
                re.IGNORECASE,
            )
            if not pattern.search(explainer_source):
                fact_problems.append(
                    f"{EXPLAINER_FILE} does not bind {fact_key}={value}"
                )

        allowed_time_facts = {
            (str(cycle_days), "天"),
            (str(cycle_hours), "小时"),
        }
        for number, unit in re.findall(r"(?<!\d)(\d+)\s*(天|小时)", explainer_text):
            if (number, unit) not in allowed_time_facts:
                fact_problems.append(
                    f"{EXPLAINER_FILE} has unsupported time fact {number} {unit}"
                )

        page_terminology = facts["page_terminology"]
        assert isinstance(page_terminology, dict)
        required_keywords = (
            "税务 App",
            str(page_terminology["must_use"]),
        )
        for keyword in required_keywords:
            if keyword not in explainer_text:
                fact_problems.append(f"{EXPLAINER_FILE} lacks keyword {keyword!r}")

    checks.record(
        "Explainer — fact consistency",
        fact_problems,
        "all page-approved facts.json copy is present; 183-day and 24-hour bindings match exactly; required account-mode terminology is present",
    )

    term_problems: list[str] = []
    if not explainer_source:
        term_problems.append(f"{EXPLAINER_FILE} unavailable")
    else:
        for term in FORBIDDEN_TERMS:
            if term in explainer_source:
                term_problems.append(
                    f"{EXPLAINER_FILE} contains forbidden term {term!r}"
                )
        if facts:
            page_terminology = facts["page_terminology"]
            assert isinstance(page_terminology, dict)
            forbidden_on_page = page_terminology["forbidden_on_page"]
            assert isinstance(forbidden_on_page, list)
            terms_to_scan = {
                *EXPLAINER_PAGE_FORBIDDEN_TERMS,
                *(str(term) for term in forbidden_on_page),
            }
            for term in sorted(terms_to_scan):
                occurrence_count = explainer_source.count(term)
                if occurrence_count:
                    term_problems.append(
                        f"{EXPLAINER_FILE} contains forbidden page term "
                        f"{term!r} {occurrence_count} time(s); expected 0"
                    )
        if re.search(r"15\s*天\s*退\s*款", explainer_source):
            term_problems.append(
                f"{EXPLAINER_FILE} contains an unsupported 15-day refund promise"
            )
        if "\u65e0\u7406\u7531\u9000\u6b3e" in explainer_source:
            term_problems.append(
                f"{EXPLAINER_FILE} contains an unsupported no-reason refund promise"
            )

        unsupported_tax_patterns = {
            "unlisted tax-rate claim": r"(?<![\w.])\d+(?:\.\d+)?\s*%",
            "guaranteed tax outcome": (
                r"(?:保证|承诺|确保).{0,12}(?:开票成功|开票额度|税率|免税)"
            ),
            "permanent authentication claim": r"(?:永久|终身).{0,8}(?:认证|有效)",
            "authentication bypass claim": (
                r"(?:无需|不用)(?:再|另外)?(?:做|进行|完成)?"
                r"(?:实名|扫脸|验证码|认证)"
            ),
            "automated real-person authentication claim": (
                r"自动.{0,8}(?:扫脸|输入.{0,4}验证码|完成.{0,4}认证)"
            ),
            "channel choice or switching copy": (
                r"(?:选择|切换)通道|通道(?:选择|切换)"
            ),
        }
        visible_text = explainer_parser.text
        for label, pattern in unsupported_tax_patterns.items():
            if re.search(pattern, visible_text):
                term_problems.append(
                    f"{EXPLAINER_FILE} contains {label} not supported by facts.json"
                )

    checks.record(
        "Explainer — forbidden terms",
        term_problems,
        "RPA/乐企 each occur 0 times; site-wide bans and unsupported tax-rate, guarantee, bypass, permanence, auto-auth, and channel-switch claims are absent",
    )

    link_problems: list[str] = []
    for file_name in (EXPLAINER_FILE, *EXPLAINER_ASSETS):
        if not (ROOT / file_name).is_file():
            link_problems.append(f"missing {file_name}")

    for source_name in HTML_FILES:
        parser = parsers.get(source_name)
        if parser is None:
            link_problems.append(f"{source_name} unavailable")
            continue
        explainer_links = [
            link
            for link in parser.links
            if isinstance(link["attrs"], dict)
            and link["attrs"].get("href") == EXPLAINER_FILE
        ]
        if len(explainer_links) != 2:
            link_problems.append(
                f"{source_name} must link to {EXPLAINER_FILE} exactly twice "
                f"(found {len(explainer_links)})"
            )

    if explainer_source:
        expected_asset_refs = {
            ("link", "href", "assets/style.css"),
            ("link", "href", "assets/explainer.css"),
            ("script", "src", "assets/explainer.js"),
        }
        actual_asset_refs = set(explainer_parser.asset_refs)
        for reference in sorted(expected_asset_refs - actual_asset_refs):
            link_problems.append(
                f"{EXPLAINER_FILE} lacks local asset reference {reference[2]}"
            )

        for tag, attr, value in explainer_parser.asset_refs:
            if is_external_reference(value):
                link_problems.append(
                    f"{EXPLAINER_FILE} loads external {tag} {attr}: {value}"
                )

        pricing_path = ROOT / "pricing.json"
        try:
            pricing = json.loads(pricing_path.read_text(encoding="utf-8"))
            service_entity = str(pricing["service_entity"])
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError) as exc:
            link_problems.append(f"cannot verify service entity ({exc})")
        else:
            if service_entity not in explainer_parser.text:
                link_problems.append(
                    f"{EXPLAINER_FILE} service entity differs from pricing.json"
                )

    checks.record(
        "Explainer — links and files",
        link_problems,
        "three explainer deliverables exist; index and guide each provide header and content links; local assets and service entity are verified",
    )

    motion_problems: list[str] = []
    css_path = ROOT / EXPLAINER_ASSETS[0]
    js_path = ROOT / EXPLAINER_ASSETS[1]
    try:
        explainer_css = css_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        explainer_css = ""
        motion_problems.append(f"cannot read {EXPLAINER_ASSETS[0]} ({exc})")
    try:
        explainer_js = js_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        explainer_js = ""
        motion_problems.append(f"cannot read {EXPLAINER_ASSETS[1]} ({exc})")

    if explainer_css and not re.search(
        r"@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)",
        explainer_css,
        re.IGNORECASE,
    ):
        motion_problems.append(
            f"{EXPLAINER_ASSETS[0]} lacks prefers-reduced-motion: reduce"
        )
    if explainer_css and not re.search(
        r"prefers-reduced-motion[\s\S]*?animation\s*:\s*none\s*!important",
        explainer_css,
        re.IGNORECASE,
    ):
        motion_problems.append(
            f"{EXPLAINER_ASSETS[0]} does not disable animation for reduced motion"
        )
    if explainer_js and "IntersectionObserver" not in explainer_js:
        motion_problems.append(
            f"{EXPLAINER_ASSETS[1]} does not use IntersectionObserver"
        )
    if explainer_js and "prefers-reduced-motion: reduce" not in explainer_js:
        motion_problems.append(
            f"{EXPLAINER_ASSETS[1]} does not react to reduced-motion preference"
        )
    if explainer_css and not re.search(
        r"overflow-x\s*:\s*(?:clip|hidden)", explainer_css, re.IGNORECASE
    ):
        motion_problems.append(
            f"{EXPLAINER_ASSETS[0]} lacks a horizontal overflow guard"
        )
    if explainer_css and re.search(r"\b100vw\b", explainer_css):
        motion_problems.append(
            f"{EXPLAINER_ASSETS[0]} uses 100vw, a common mobile overflow source"
        )

    if explainer_source:
        svg_count = len(re.findall(r"<svg\b", explainer_source, re.IGNORECASE))
        if svg_count < 4:
            motion_problems.append(
                f"{EXPLAINER_FILE} needs multiple inline SVG illustrations"
            )
        if re.search(r"<(?:img|image)\b", explainer_source, re.IGNORECASE):
            motion_problems.append(
                f"{EXPLAINER_FILE} must use inline SVG instead of image files"
            )
        if re.search(
            r"<svg\b[\s\S]*?(?:href|src)\s*=\s*[\"'](?:https?:)?//",
            explainer_source,
            re.IGNORECASE,
        ):
            motion_problems.append(
                f"{EXPLAINER_FILE} inline SVG contains an external reference"
            )
    else:
        motion_problems.append(f"{EXPLAINER_FILE} unavailable")

    combined_assets = "\n".join((explainer_source, explainer_css, explainer_js))
    if re.search(
        r"@import\b|url\(\s*['\"]?(?:https?:)?//|"
        r"\b(?:react|react-dom|vue|angular|bootstrap|tailwind)(?:\.min)?\.(?:js|css)\b",
        combined_assets,
        re.IGNORECASE,
    ):
        motion_problems.append("explainer contains an external or framework asset")

    checks.record(
        "Explainer — motion and inline SVG",
        motion_problems,
        "IntersectionObserver, reduced-motion fallback, mobile overflow guard, inline SVG, and local zero-framework assets are present",
    )


def check_manual(checks: Checks) -> None:
    problems: list[str] = []
    page_sources: dict[str, str] = {}

    for name in NAV_PAGE_FILES:
        path = ROOT / name
        try:
            page_sources[name] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            problems.append(f"cannot read {name} ({exc})")

    for name in NAV_PAGE_FILES:
        source = page_sources.get(name)
        if source is None:
            continue
        header_match = re.search(
            r"<header\b[^>]*>[\s\S]*?</header>",
            source,
            re.IGNORECASE,
        )
        if header_match is None:
            problems.append(f"{name} lacks a header navigation block")
            continue
        header_hrefs = set(
            re.findall(
                r"\bhref\s*=\s*[\"']([^\"']+)[\"']",
                header_match.group(0),
                re.IGNORECASE,
            )
        )
        for target in NAV_PAGE_FILES:
            if target not in header_hrefs:
                problems.append(f"{name} header does not link to {target}")

    manual_source = page_sources.get(MANUAL_FILE)
    if manual_source is not None:
        manual_parser = SiteHTMLParser()
        manual_parser.feed(manual_source)
        manual_parser.close()
        manual_text = manual_parser.text

        for term in (*MANUAL_PAGE_FORBIDDEN_TERMS, *SITE_FORBIDDEN_VENDOR_TERMS):
            occurrence_count = (
                count_vendor_mentions(manual_source)
                if term in SITE_FORBIDDEN_VENDOR_TERMS
                else manual_source.count(term)
            )
            if occurrence_count:
                problems.append(
                    f"{MANUAL_FILE} contains forbidden term {term!r} "
                    f"{occurrence_count} time(s); expected 0"
                )
        for code in MANUAL_FORBIDDEN_ERROR_CODES:
            # 扫原始源码而不是解析后的可见文本，和紧邻的禁用词守卫对齐：
            # 码写进 title 属性（浏览器原生 tooltip）或 href 查询串照样被商户看到。
            occurrence_count = manual_source.count(code)
            if occurrence_count:
                problems.append(
                    f"{MANUAL_FILE} exposes upstream error code {code} "
                    f"{occurrence_count} time(s); expected 0 — describe the problem "
                    f"in plain Chinese instead"
                )
        for marker in MANUAL_TICKET_MARKERS:
            if marker not in manual_text:
                problems.append(
                    f"{MANUAL_FILE} lacks the support-ticket entry marker {marker!r}"
                )
        # 「显著位置」要断结构，不能只断词：顶部常驻板块 + 目录里的跳转项都必须在，
        # 且板块要排在第一个正文章节（manual-chapter）之前，否则等于又退回
        # 「联系方式埋在最后一屏」。板块本身在 hero 里，所以不能拿 <section> 当界标。
        ticket_anchor = manual_source.find('id="ticket"')
        if ticket_anchor < 0:
            problems.append(
                f"{MANUAL_FILE} lacks the prominent support-ticket block (id=\"ticket\")"
            )
        elif 0 <= manual_source.find('class="manual-chapter"') < ticket_anchor:
            problems.append(
                f"{MANUAL_FILE} support-ticket block is below the first chapter; "
                f"it must stay near the top"
            )
        if 'href="#ticket"' not in manual_source:
            problems.append(f"{MANUAL_FILE} table of contents lacks the #ticket entry")
        if ticket_anchor >= 0:
            # 只断言锚点在不行：板块里的文字和去注册页的唯一链接被删光，锚点还在也能过。
            ticket_block = manual_source[ticket_anchor : manual_source.find("</div>", ticket_anchor)]
            for required in ("提交工单", 'href="https://fapiao.chinavtax.com/register"'):
                if required not in ticket_block:
                    problems.append(
                        f"{MANUAL_FILE} support-ticket block lacks {required!r}"
                    )
        for duration in MANUAL_DURATION_RANGES:
            if duration not in manual_text:
                problems.append(
                    f"{MANUAL_FILE} lacks duration range {duration!r}"
                )
        if MANUAL_SOURCE_ATTRIBUTION not in manual_text:
            problems.append(
                f"{MANUAL_FILE} lacks source attribution "
                f"{MANUAL_SOURCE_ATTRIBUTION!r}"
            )
        if 'href="assets/manual.pdf"' not in manual_source:
            problems.append(f"{MANUAL_FILE} lacks the assets/manual.pdf download link")

    pdf_path = ROOT / "assets" / "manual.pdf"
    stamp_path = ROOT / "assets" / "manual.pdf.source"
    if not pdf_path.is_file():
        problems.append("assets/manual.pdf is missing; regenerate it after manual content changes (see README)")
    else:
        size = pdf_path.stat().st_size
        # 20_000 这个旧阈值拦不住任何已知故障：一次渲染失败的产物是 68914 字节，
        # 正常导出是 740K~800K。按真实体量设下限，坏导出才会被挡下。
        if size < MANUAL_PDF_MIN_BYTES:
            problems.append(
                f"assets/manual.pdf looks truncated ({size} bytes < {MANUAL_PDF_MIN_BYTES}); "
                f"re-export it and check the text layer (see README)"
            )
        # PDF 是导出件，check.py 读不了它的文本层（纯 stdlib）。改用指纹拦住唯一的
        # 真实故障路径：manual.html 改了却忘记重新导出，商户下载到的仍是旧手册。
        # 两个摘要都要记：只记 HTML 的话，把旧 PDF 原样拷回来（HTML 没动）照样能过，
        # 而那份旧 PDF 里印着 8047/3001/8011。
        expected = {
            "manual_html": hashlib.sha256((ROOT / MANUAL_FILE).read_bytes()).hexdigest(),
            "manual_pdf": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        }
        if not stamp_path.is_file():
            problems.append(
                "assets/manual.pdf.source is missing; re-export the PDF and record the "
                "digests (see README)"
            )
        else:
            try:
                recorded = json.loads(stamp_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                recorded = {}
            if recorded.get("manual_html") != expected["manual_html"]:
                problems.append(
                    "assets/manual.pdf is stale: manual.html changed since the last export. "
                    "Re-export the PDF and refresh assets/manual.pdf.source (see README)"
                )
            elif recorded.get("manual_pdf") != expected["manual_pdf"]:
                problems.append(
                    "assets/manual.pdf is not the file that was exported from the current "
                    "manual.html (digest mismatch). Re-export it and refresh "
                    "assets/manual.pdf.source (see README)"
                )

    style_source = (ROOT / "assets" / "style.css").read_text(encoding="utf-8")
    if "@media print" not in style_source:
        problems.append("assets/style.css lacks the @media print block for PDF/print export")

    checks.record(
        "manual",
        problems,
        "four-page header navigation is cross-linked; forbidden terms and upstream error codes occur 0 times; support-ticket entry, duration ranges, source attribution, PDF download link/file, and print styles are present",
    )


def main() -> int:
    checks = Checks()
    pricing, sources, parsers = load_sources(checks)
    if pricing and len(sources) == len(HTML_FILES):
        check_pricing(checks, pricing, sources, parsers)
        check_copy(checks, sources, parsers)
        check_images(checks, parsers)
        check_ctas_and_assets(checks, parsers)
        check_responsive_contract(checks, sources, parsers)
        check_static_stack(checks, sources)
    else:
        checks.record(
            "Site content checks",
            ["cannot continue because pricing.json or HTML files are unavailable"],
            "",
        )
    check_explainer(checks, sources, parsers)
    check_manual(checks)
    check_message_form(checks)
    check_dealer_poster(checks, pricing)
    if (ROOT / "README.md").is_file():
        check_readme(checks)
    return checks.emit()


if __name__ == "__main__":
    sys.exit(main())
