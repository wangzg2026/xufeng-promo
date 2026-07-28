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
REQUIRED_FILES = (*HTML_FILES, "assets/style.css", "check.py", "README.md")
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
    if (ROOT / "README.md").is_file():
        check_readme(checks)
    return checks.emit()


if __name__ == "__main__":
    sys.exit(main())
