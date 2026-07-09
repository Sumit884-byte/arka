#!/usr/bin/env python3
"""Currency conversion using live exchange rates (Frankfurter + open.er-api fallback)."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

USER_AGENT = "Mozilla/5.0 (compatible; Arka/1.0)"

# ISO 4217 codes and common aliases / plural forms.
CURRENCY_ALIASES: dict[str, str] = {
    "usd": "USD",
    "dollar": "USD",
    "dollars": "USD",
    "us dollar": "USD",
    "us dollars": "USD",
    "american dollar": "USD",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "inr": "INR",
    "rupee": "INR",
    "rupees": "INR",
    "rs": "INR",
    "₹": "INR",
    "gbp": "GBP",
    "pound": "GBP",
    "pounds": "GBP",
    "sterling": "GBP",
    "british pound": "GBP",
    "british pounds": "GBP",
    "jpy": "JPY",
    "yen": "JPY",
    "japanese yen": "JPY",
    "cad": "CAD",
    "canadian dollar": "CAD",
    "canadian dollars": "CAD",
    "aud": "AUD",
    "australian dollar": "AUD",
    "australian dollars": "AUD",
    "chf": "CHF",
    "swiss franc": "CHF",
    "swiss francs": "CHF",
    "cny": "CNY",
    "yuan": "CNY",
    "renminbi": "CNY",
    "rmb": "CNY",
    "sgd": "SGD",
    "singapore dollar": "SGD",
    "singapore dollars": "SGD",
    "aed": "AED",
    "dirham": "AED",
    "dirhams": "AED",
    "hkd": "HKD",
    "hong kong dollar": "HKD",
    "nzd": "NZD",
    "new zealand dollar": "NZD",
    "krw": "KRW",
    "won": "KRW",
    "korean won": "KRW",
    "mxn": "MXN",
    "peso": "MXN",
    "pesos": "MXN",
    "brl": "BRL",
    "real": "BRL",
    "reais": "BRL",
    "zar": "ZAR",
    "rand": "ZAR",
    "sek": "SEK",
    "krona": "SEK",
    "nok": "NOK",
    "krone": "NOK",
    "dkk": "DKK",
    "try": "TRY",
    "lira": "TRY",
    "thb": "THB",
    "baht": "THB",
    "php": "PHP",
    "myr": "MYR",
    "ringgit": "MYR",
    "idr": "IDR",
    "rupiah": "IDR",
    "pln": "PLN",
    "zloty": "PLN",
    "ils": "ILS",
    "shekel": "ILS",
    "shekels": "ILS",
}

KNOWN_CODES = frozenset(set(CURRENCY_ALIASES.values()))

_CURRENCY_NAMES = (
    r"usd|eur|inr|gbp|jpy|cad|aud|chf|cny|sgd|aed|hkd|nzd|krw|mxn|brl|zar|"
    r"sek|nok|dkk|try|thb|php|myr|idr|pln|ils|"
    r"dollars?|euros?|rupees?|pounds?|sterling|yen|yuan|renminbi|rmb|"
    r"dirhams?|pesos?|reais?|rand|krona|krone|lira|baht|ringgit|rupiah|zloty|shekels?"
)
_CURRENCY_TOKEN = rf"({_CURRENCY_NAMES})"

_KNOWN_CMDS = frozenset({"parse", "convert"})


@dataclass(frozen=True)
class ConversionResult:
    amount: Decimal
    from_ccy: str
    to_ccy: str
    rate: Decimal
    result: Decimal
    date: str
    source: str


def normalize_currency(token: str) -> str | None:
    """Map a currency token or name to an ISO 4217 code."""
    raw = (token or "").strip()
    if not raw:
        return None
    cleaned = re.sub(r"[^\w₹$€£]", "", raw.lower())
    if not cleaned:
        return None
    if len(cleaned) == 3 and cleaned.isalpha():
        code = cleaned.upper()
        return code if code in KNOWN_CODES else None
    return CURRENCY_ALIASES.get(cleaned)


def _parse_amount(token: str) -> Decimal | None:
    raw = (token or "").strip().replace(",", "")
    if not raw:
        return None
    try:
        return Decimal(raw)
    except Exception:
        return None


def parse_convert(text: str) -> tuple[Decimal, str, str] | None:
    """Parse natural language or direct args into (amount, from_ccy, to_ccy)."""
    t = (text or "").strip()
    if not t:
        return None

    # Strip leading command words.
    t = re.sub(
        r"(?i)^(?:please\s+)?(?:currency(?:\s+convert)?|convert|exchange|what\s+is|how\s+much\s+is)\s+",
        "",
        t,
    ).strip()
    t = re.sub(r"(?i)^(?:the\s+)?(?:exchange\s+rate\s+for\s+)", "", t).strip()

    # "100 USD to INR" / "50 euros to dollars" / "what is 500 EUR in GBP"
    m = re.search(
        rf"(?i)(\d[\d,]*(?:\.\d+)?)\s*{_CURRENCY_TOKEN}\s*(?:to|in|into)\s*{_CURRENCY_TOKEN}",
        t,
    )
    if m:
        amount = _parse_amount(m.group(1))
        from_ccy = normalize_currency(m.group(2))
        to_ccy = normalize_currency(m.group(3))
        if amount is not None and from_ccy and to_ccy:
            return amount, from_ccy, to_ccy

    # "USD to INR" with default amount 1 (exchange rate query)
    m = re.search(
        rf"(?i)^(?:exchange\s+rate\s+)?{_CURRENCY_TOKEN}\s*(?:to|in|into)\s*{_CURRENCY_TOKEN}$",
        t,
    )
    if m:
        from_ccy = normalize_currency(m.group(1))
        to_ccy = normalize_currency(m.group(2))
        if from_ccy and to_ccy:
            return Decimal("1"), from_ccy, to_ccy

    # Positional: "100 USD INR"
    parts = shlex.split(t, posix=True)
    if len(parts) >= 3:
        amount = _parse_amount(parts[0])
        from_ccy = normalize_currency(parts[1])
        to_ccy = normalize_currency(parts[2])
        if amount is not None and from_ccy and to_ccy:
            return amount, from_ccy, to_ccy

    if len(parts) == 2:
        from_ccy = normalize_currency(parts[0])
        to_ccy = normalize_currency(parts[1])
        if from_ccy and to_ccy:
            return Decimal("1"), from_ccy, to_ccy

    return None


def _format_amount(amount: Decimal) -> str:
    text = format(amount.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def nl_to_argv(text: str) -> list[str]:
    """Parse natural language into currency_convert argv: amount from to."""
    parsed = parse_convert(text)
    if not parsed:
        return []
    amount, from_ccy, to_ccy = parsed
    return [_format_amount(amount), from_ccy, to_ccy]


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _fetch_frankfurter(amount: Decimal, from_ccy: str, to_ccy: str) -> ConversionResult:
    amt = format(amount.normalize(), "f")
    url = (
        f"https://api.frankfurter.app/latest?"
        f"amount={urllib.parse.quote(amt)}&from={from_ccy}&to={to_ccy}"
    )
    data = _fetch_json(url)
    rates = data.get("rates") or {}
    if to_ccy not in rates:
        raise ValueError(f"No rate for {to_ccy}")
    result = Decimal(str(rates[to_ccy]))
    rate = (result / amount) if amount else Decimal("0")
    return ConversionResult(
        amount=amount,
        from_ccy=from_ccy,
        to_ccy=to_ccy,
        rate=rate,
        result=result,
        date=str(data.get("date") or "unknown"),
        source="Frankfurter (ECB)",
    )


def _fetch_open_er_api(amount: Decimal, from_ccy: str, to_ccy: str) -> ConversionResult:
    url = f"https://open.er-api.com/v6/latest/{from_ccy}"
    data = _fetch_json(url)
    if data.get("result") != "success":
        raise ValueError("open.er-api request failed")
    rates = data.get("rates") or {}
    if to_ccy not in rates:
        raise ValueError(f"No rate for {to_ccy}")
    rate = Decimal(str(rates[to_ccy]))
    result = (amount * rate).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return ConversionResult(
        amount=amount,
        from_ccy=from_ccy,
        to_ccy=to_ccy,
        rate=rate,
        result=result,
        date=str((data.get("time_last_update_utc") or "unknown")).split(" ")[0],
        source="open.er-api.com",
    )


def fetch_conversion(amount: Decimal, from_ccy: str, to_ccy: str) -> ConversionResult:
    """Fetch live conversion; tries Frankfurter first, then open.er-api."""
    errors: list[str] = []
    for fetcher in (_fetch_frankfurter, _fetch_open_er_api):
        try:
            return fetcher(amount, from_ccy, to_ccy)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, KeyError) as exc:
            errors.append(str(exc))
    raise RuntimeError(
        f"Could not fetch exchange rate for {from_ccy} → {to_ccy}. "
        + ("; ".join(errors) if errors else "network error")
    )


def convert(amount: Decimal, from_ccy: str, to_ccy: str) -> ConversionResult:
    """Convert amount between currencies."""
    from_code = normalize_currency(from_ccy)
    to_code = normalize_currency(to_ccy)
    if not from_code:
        raise ValueError(f"Unknown currency: {from_ccy!r}")
    if not to_code:
        raise ValueError(f"Unknown currency: {to_ccy!r}")
    if from_code == to_code:
        return ConversionResult(
            amount=amount,
            from_ccy=from_code,
            to_ccy=to_code,
            rate=Decimal("1"),
            result=amount,
            date="n/a",
            source="identity",
        )
    return fetch_conversion(amount, from_code, to_code)


def format_result(conv: ConversionResult) -> str:
    """Pretty terminal output for a conversion."""
    amt = _format_amount(conv.amount)
    res = _format_amount(conv.result)
    rate = format(conv.rate.normalize(), ",.6f").rstrip("0").rstrip(".")
    lines = [
        "━━━ Currency Conversion ━━━",
        f"  {amt} {conv.from_ccy}  →  {res} {conv.to_ccy}",
        f"  Rate:     1 {conv.from_ccy} = {rate} {conv.to_ccy}",
        f"  Source:   {conv.source}",
        f"  As of:    {conv.date}",
    ]
    return "\n".join(lines)


def cmd_convert(argv: list[str]) -> int:
    text = " ".join(argv).strip()
    if not text:
        print(
            "Usage: currency_convert <amount> <from> <to>\n"
            "       currency_convert convert 100 USD to INR\n"
            "       arka 'what is 500 EUR in GBP'",
            file=sys.stderr,
        )
        return 1
    parsed = parse_convert(text)
    if not parsed:
        print(
            f"Could not parse currency conversion: {text!r}\n"
            "Examples:\n"
            "  currency_convert 100 USD INR\n"
            "  convert 50 euros to dollars\n"
            "  what is 1000 rupees to usd",
            file=sys.stderr,
        )
        return 1
    amount, from_ccy, to_ccy = parsed
    try:
        result = convert(amount, from_ccy, to_ccy)
    except ValueError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    print(format_result(result))
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "Usage: arka_currency.py [convert] <amount> <from> <to>\n"
            "       arka_currency.py parse <natural language>",
            file=sys.stderr,
        )
        return 0 if not argv else 1

    if argv[0] == "parse":
        return cmd_parse(argparse.Namespace(text=argv[1:]))

    if argv[0] == "convert":
        return cmd_convert(argv[1:])

    if argv[0] not in _KNOWN_CMDS:
        return cmd_convert(argv)

    parser = argparse.ArgumentParser(description="Convert currencies using live exchange rates.")
    sub = parser.add_subparsers(dest="cmd")
    p_parse = sub.add_parser("parse", help="Parse natural language → args (internal)")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)
    sub.add_parser("convert", help="Convert amount between currencies").set_defaults(
        func=lambda a: cmd_convert(getattr(a, "rest", []))
    )
    args = parser.parse_args()
    if args.cmd is None:
        return cmd_convert(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
