#!/usr/bin/env python3
"""Self-check for the xufeng-promo static site (standard library only)."""

from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
HTML_FILES = ("index.html", "guide.html")
EXPLAINER_FILE = "invoice-explainer.html"
EXPLAINER_ASSETS = ("assets/explainer.css", "assets/explainer.js")
FACTS_FILE = "facts.json"
EXPLAINER_PAGE_FORBIDDEN_TERMS = ("RPA", "乐企")
REQUIRED_FILES = (
    *HTML_FILES,
    EXPLAINER_FILE,
    "assets/style.css",
    *EXPLAINER_ASSETS,
    FACTS_FILE,
    "check.py",
    "README.md",
)
PLACEHOLDER_IMAGES = {
    f"assets/screenshots/step-{number:02d}.png" for number in range(1, 7)
}
FORBIDDEN_TERMS = (
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
    refund_slogan = str(pricing["refund_slogan"])
    refund = str(pricing["refund_policy"])
    refund_channel = str(pricing["refund_channel"])
    entity = str(pricing["service_entity"])
    allowed_prices = {first, renewal}
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

        for amount in allowed_prices:
            for match in re.finditer(rf"(?<!\d){amount}(?!\d)", text):
                context = text[match.start() : match.end() + len(unit) + 2]
                if not re.match(rf"{amount}\s+{re.escape(unit)}", context):
                    problems.append(
                        f"{name} uses {amount} outside the exact '{unit}' price context"
                    )

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
        "step-01.png through step-06.png use safe paths, alt text, and figure captions",
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
                if "美菜 App" not in text:
                    problems.append(
                        f"{name} CTA copy must direct users to 美菜 App ({text!r})"
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
        "CTAs point only to in-page anchors and direct users back to 美菜 App; no external assets",
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
        "facts.json parses; authentication, account-mode terminology, reserved channels, flow, knowledge, and compliance fields are valid",
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
        if len(explainer_links) != 1:
            link_problems.append(
                f"{source_name} must link to {EXPLAINER_FILE} exactly once "
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
        "three explainer deliverables exist; index and guide link exactly once; local assets and service entity are verified",
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
    if (ROOT / "README.md").is_file():
        check_readme(checks)
    return checks.emit()


if __name__ == "__main__":
    sys.exit(main())
