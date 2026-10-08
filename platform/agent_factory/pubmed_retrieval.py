"""Fixed public PubMed query through managed host HTTP; no credentials or CLI.

This adapter retrieves bounded metadata abstracts, not licensed full text or
scientific synthesis. Only the trusted caller chooses live versus exact mocks.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import inspect
import re
import threading
import time
from typing import cast
from xml.etree import ElementTree

import httpx

from .orx_literature_tools import evidence_record

QUERY_ID = "public-rag-v1"
QUERY = "retrieval augmented generation"
BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
PUBLIC_DOCTYPE = '<!DOCTYPE PubmedArticleSet PUBLIC "-//NLM//DTD PubMedArticle, 1st January 2025//EN" "https://dtd.nlm.nih.gov/ncbi/pubmed/out/pubmed_250101.dtd">'
USER_AGENT = "agent-factory-public-literature/1 (bounded PubMed metadata retrieval)"
MAX_SEARCH_BYTES = 65536
MAX_XML_BYTES = 524288
MAX_TOTAL_BYTES = MAX_SEARCH_BYTES + MAX_XML_BYTES
TOTAL_TIMEOUT = 25
REQUEST_TIMEOUT = 10
MIN_REQUEST_INTERVAL = 0.35
_CODES = {"CONFIG_INVALID", "DESTINATION_DENIED", "HTTP_STATUS", "REDIRECT_DENIED", "BODY_LIMIT",
          "BODY_ENCODING", "JSON_INVALID", "XML_INVALID", "XML_ENTITY_DENIED", "SOURCE_ID_INVALID",
          "SOURCE_ID_MISMATCH", "TIMEOUT", "TRANSPORT", "PROXY", "TLS"}
_rate_lock = threading.Lock()
_last_dispatch = 0.0


class PubMedRetrievalError(RuntimeError):
    def __init__(self, code, *, http_status=None):
        self.code = code if type(code) is str and code in _CODES else "TRANSPORT"
        self.http_status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        super().__init__(self.code)


def _require(value, code):
    if not value:
        raise PubMedRetrievalError(code)


async def _throttle():
    # Coordinate this adapter's concurrent callers without binding a lock to
    # one event loop. Sleeping happens outside the short synchronous lock.
    global _last_dispatch
    while True:
        with _rate_lock:
            current = time.monotonic()
            remaining = MIN_REQUEST_INTERVAL - (current - _last_dispatch)
            if remaining <= 0:
                _last_dispatch = current
                return
        await asyncio.sleep(remaining)


def _pmid(value):
    return type(value) is str and re.fullmatch(r"[1-9][0-9]{0,19}", value) is not None


def _search_ids(raw, limit):
    try:
        value = json.loads(raw)
        ids = value["esearchresult"]["idlist"]
    except (ValueError, TypeError, KeyError, RecursionError):
        raise PubMedRetrievalError("JSON_INVALID") from None
    _require(type(ids) is list and len(ids) <= limit and all(_pmid(item) for item in ids), "SOURCE_ID_INVALID")
    _require(len(set(ids)) == len(ids), "SOURCE_ID_INVALID")
    return ids


def _records(raw, requested, evidence_mode):
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError:
        raise PubMedRetrievalError("XML_INVALID") from None
    # The exact observed public NCBI declaration is metadata only. Remove it
    # without resolving its URL; all variants, subsets and entities stay denied.
    if text.count(PUBLIC_DOCTYPE) == 1:
        text = text.replace(PUBLIC_DOCTYPE, "", 1)
    _require(not re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.IGNORECASE), "XML_ENTITY_DENIED")
    try:
        root = ElementTree.fromstring(text)
    except (ElementTree.ParseError, ValueError):
        raise PubMedRetrievalError("XML_INVALID") from None
    _require(root.tag == "PubmedArticleSet", "XML_INVALID")
    stack = [(root, 0)]
    nodes = 0
    while stack:
        node, depth = stack.pop()
        nodes += 1
        _require(nodes <= 4000 and depth <= 64, "XML_INVALID")
        stack.extend((child, depth + 1) for child in node)
    records = {}
    _require(len(root) <= len(requested), "SOURCE_ID_MISMATCH")
    for item in root:
        _require(item.tag == "PubmedArticle", "XML_INVALID")
        ids = item.findall("./MedlineCitation/PMID")
        _require(len(ids) == 1 and _pmid(ids[0].text), "SOURCE_ID_INVALID")
        identifier = cast(str, ids[0].text)
        _require(identifier in requested and identifier not in records, "SOURCE_ID_MISMATCH")
        articles = item.findall("./MedlineCitation/Article")
        _require(len(articles) == 1, "XML_INVALID")
        article = articles[0]
        titles = article.findall("./ArticleTitle")
        _require(len(titles) <= 1, "XML_INVALID")
        title = "".join(titles[0].itertext()).strip() if titles else ""
        abstract = "\n".join("".join(part.itertext()).strip() for part in article.findall("./Abstract/AbstractText")).strip()
        record = evidence_record(identifier, abstract, status="abstract_only" if abstract else "metadata_only",
                                 field="abstract", title=title)
        record.update(evidenceKind="controlled_literature_fixture" if evidence_mode == "controlled-fixture" else "public_literature_excerpt",
                      licenseStatus="unverified")
        records[identifier] = record
    _require(set(records) == set(requested), "SOURCE_ID_MISMATCH")
    return [records[identifier] for identifier in requested]


async def retrieve(query_id=QUERY_ID, limit=2, transport=None, *, before_dispatch=None):
    """Two requests at most; IDs from this exact search alone authorize fetch."""
    _require(type(query_id) is str and query_id == QUERY_ID and type(limit) is int and 1 <= limit <= 3, "CONFIG_INVALID")
    _require(transport is None or type(transport) is httpx.MockTransport, "CONFIG_INVALID")
    _require(before_dispatch is None or callable(before_dispatch), "CONFIG_INVALID")
    authority_error = None
    evidence_mode = "controlled-fixture" if transport is not None else "live-public-fetch"
    permitted = []

    async def guard(request):
        _require(request.method == "GET" and str(request.url) in permitted and request.url.scheme == "https"
                 and request.url.host == "eutils.ncbi.nlm.nih.gov" and request.url.port in {None, 443}
                 and not request.url.userinfo and not request.url.fragment, "DESTINATION_DENIED")
        for key in ("authorization", "cookie"):
            request.headers.pop(key, None)

    total = 0
    receipts = []
    try:
        async with asyncio.timeout(TOTAL_TIMEOUT):
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, transport=transport, trust_env=transport is None,
                    verify=True, follow_redirects=False, auth=None, headers={"User-Agent": USER_AGENT,
                    "Accept-Encoding": "identity"}, event_hooks={"request": [guard]}) as client:
                async def fetch(endpoint, params, bound):
                    nonlocal total, authority_error
                    url = httpx.URL(BASE + endpoint, params=params)
                    permitted[:] = [str(url)]
                    await _throttle()
                    if before_dispatch is not None:
                        try:
                            result = before_dispatch()
                            # Async authority checks would otherwise be silently
                            # skipped; this contract explicitly requires sync.
                            if inspect.isawaitable(result):
                                if inspect.iscoroutine(result):
                                    result.close()
                                raise PubMedRetrievalError("CONFIG_INVALID")
                        except BaseException as error:
                            authority_error = error
                            raise
                    async with client.stream("GET", url) as response:
                        _require(not 300 <= response.status_code <= 399, "REDIRECT_DENIED")
                        if response.status_code != 200:
                            raise PubMedRetrievalError("HTTP_STATUS", http_status=response.status_code)
                        _require(response.headers.get("content-encoding", "identity").lower() == "identity", "BODY_ENCODING")
                        body = bytearray()
                        async for chunk in response.aiter_raw():
                            total += len(chunk)
                            _require(len(body) + len(chunk) <= bound and total <= MAX_TOTAL_BYTES, "BODY_LIMIT")
                            body.extend(chunk)
                        raw = bytes(body)
                        receipts.append({"endpoint": endpoint, "httpStatus": 200, "byteCount": len(raw),
                                         "sha256": hashlib.sha256(raw).hexdigest()})
                        return raw
                search = await fetch("esearch.fcgi", {"db": "pubmed", "term": QUERY, "retmode": "json",
                                                       "retmax": str(limit)}, MAX_SEARCH_BYTES)
                ids = _search_ids(search, limit)
                sources = []
                if ids:
                    xml = await fetch("efetch.fcgi", {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}, MAX_XML_BYTES)
                    sources = _records(xml, ids, evidence_mode)
    except asyncio.CancelledError:
        raise
    except PubMedRetrievalError:
        raise
    except (TimeoutError, httpx.TimeoutException) as error:
        if error is authority_error:
            raise
        raise PubMedRetrievalError("TIMEOUT") from None
    except httpx.ProxyError as error:
        if error is authority_error:
            raise
        raise PubMedRetrievalError("PROXY") from None
    except (httpx.HTTPError, OSError) as error:
        if error is authority_error:
            raise
        raise PubMedRetrievalError("TRANSPORT") from None
    return {"mode": "bibliography-excerpts-no-provider", "evidenceMode": evidence_mode, "sources": sources,
            "provenance": {"queryId": QUERY_ID, "corpus": "pubmed", "limit": limit,
                "transport": "managed-host-http", "containerIsolation": False, "licenseStatus": "unverified",
                "fullTextRetrieved": False, "providerCalled": False, "responses": receipts}}
