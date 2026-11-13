"""Content extractor and HTML cleaner for novel chapters."""

import re
import urllib.parse
from typing import Optional
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from novel_scraper.exceptions import ChapterExtractionError

TAGS_TO_REMOVE = {
    "script",
    "style",
    "noscript",
    "iframe",
    "svg",
    "button",
    "input",
    "form",
    "header",
    "footer",
    "nav",
    "aside",
    "select",
    "option",
    "audio",
    "video",
}

CLASS_ID_BLACKLIST_PATTERNS = [
    re.compile(r"\b(ad|ads|advertisement|banner|social|share|share-box)\b", re.IGNORECASE),
    re.compile(r"\b(comment|comments|reply|rating|feedback|review)\b", re.IGNORECASE),
    re.compile(r"\b(hidden|sr-only|popup|modal|auth-gate)\b", re.IGNORECASE),
]

ALLOWED_TAGS = {
    "p",
    "br",
    "hr",
    "em",
    "strong",
    "b",
    "i",
    "u",
    "s",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "img",
    "span",
}


class ContentExtractor:
    """Extracts and sanitizes readable chapter content into clean XHTML."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url

    def clean(self, raw_html: str, container_selector: Optional[str] = None) -> tuple[str, list[str]]:
        """Parse raw HTML, isolate chapter content, strip noise, and format clean XHTML.

        Returns:
            A tuple of (clean_xhtml_str, list_of_paragraph_strings).
        """
        if not raw_html or not raw_html.strip():
            raise ChapterExtractionError("Empty HTML provided to content extractor.")

        soup = BeautifulSoup(raw_html, "lxml")

        # Locate the content container if selector is specified
        if container_selector:
            container = soup.select_one(container_selector)
            if not container:
                # Try fallback heuristics if selector not found
                container = self._find_fallback_container(soup)
        else:
            container = self._find_fallback_container(soup)

        if not container:
            raise ChapterExtractionError("Could not locate chapter content container.")

        # 1. Remove HTML comments
        for comment in container.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        # 2. Decompose blacklisted tags
        for tag_name in TAGS_TO_REMOVE:
            for elem in container.find_all(tag_name):
                elem.decompose()

        # 3. Decompose elements matching blacklisted classes or ids
        for elem in list(container.find_all(True)):
            if elem.decomposed:
                continue
            classes = elem.get("class") or []
            if isinstance(classes, list):
                class_str = " ".join(classes)
            else:
                class_str = str(classes)
            elem_id = elem.get("id") or ""

            target_str = f"{class_str} {elem_id}"
            if any(pat.search(target_str) for pat in CLASS_ID_BLACKLIST_PATTERNS):
                elem.decompose()

        # 4. Clean tags and attributes
        cleaned_elements: list[Tag] = []
        paragraphs_text: list[str] = []

        # Find all paragraph elements or block-level elements
        children = list(container.children)
        # Check if content consists of direct <p> tags
        p_tags = container.find_all("p")
        if p_tags:
            for p in p_tags:
                self._sanitize_tag(p)
                raw_text = p.get_text()
                normalized_text = re.sub(r"\s+", " ", raw_text).strip()
                if normalized_text or p.find("img"):
                    cleaned_elements.append(p)
                    if normalized_text:
                        paragraphs_text.append(normalized_text)
        else:
            # Fallback for text separated by <br> or bare text nodes
            text_blocks = self._extract_text_blocks(container)
            for block in text_blocks:
                normalized_block = re.sub(r"\s+", " ", block).strip()
                p_tag = soup.new_tag("p")
                p_tag.string = normalized_block
                cleaned_elements.append(p_tag)
                paragraphs_text.append(normalized_block)

        if not paragraphs_text and not container.find("img"):
            raise ChapterExtractionError("Extracted chapter content is empty.")

        # Assemble clean XHTML
        clean_soup = BeautifulSoup(
            '<div class="chapter-content"></div>',
            "lxml",
        )
        content_div = clean_soup.div
        for elem in cleaned_elements:
            content_div.append(elem)

        # Convert to strict XHTML format
        clean_xhtml = "".join(str(elem) for elem in content_div.children)
        # Ensure self-closing tags like img and br are valid XML
        clean_xhtml = re.sub(r"<img([^>]*[^/])>", r"<img\1 />", clean_xhtml)
        clean_xhtml = re.sub(r"<br([^>]*[^/])>", r"<br\1 />", clean_xhtml)
        clean_xhtml = re.sub(r"<hr([^>]*[^/])>", r"<hr\1 />", clean_xhtml)

        return clean_xhtml, paragraphs_text

    def _find_fallback_container(self, soup: BeautifulSoup) -> Optional[Tag]:
        """Heuristic discovery for chapter text container."""
        candidates = [
            "#chr-content",
            ".chr-c",
            "#chapter-content",
            ".chapter-content",
            "#content",
            ".reading-content",
            ".entry-content",
            "article",
        ]
        for sel in candidates:
            found = soup.select_one(sel)
            if found:
                return found
        # Fallback to body
        return soup.body

    def _sanitize_tag(self, tag: Tag) -> None:
        """Sanitize an individual tag and its children."""
        for child in list(tag.find_all(True)):
            if child.name not in ALLOWED_TAGS:
                child.unwrap()
            else:
                self._clean_attributes(child)
        self._clean_attributes(tag)

    def _clean_attributes(self, tag: Tag) -> None:
        """Strip dangerous or unwanted attributes while preserving necessary ones."""
        allowed_attrs = {"src", "alt", "title"} if tag.name == "img" else set()
        attrs_to_remove = [k for k in tag.attrs if k not in allowed_attrs]
        for attr in attrs_to_remove:
            del tag[attr]

        # Fix relative image URLs
        if tag.name == "img" and "src" in tag.attrs and self.base_url:
            tag["src"] = urllib.parse.urljoin(self.base_url, tag["src"])

    def _extract_text_blocks(self, container: Tag) -> list[str]:
        """Extract separated paragraphs from containers with loose <br> tags."""
        text = container.decode_contents()
        # Replace breaks with newlines
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        # Strip all other HTML
        soup = BeautifulSoup(text, "lxml")
        clean_text = soup.get_text()
        blocks = [line.strip() for line in clean_text.splitlines() if line.strip()]
        return blocks
