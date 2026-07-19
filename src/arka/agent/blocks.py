"""Inspectable reusable application blocks with stack guidance."""
from __future__ import annotations

import argparse
import json
import re
import shlex
from pathlib import Path

BLOCKS = {
    "auth_login": {"kind": "auth", "stacks": ["Next.js + Auth.js", "React + Supabase Auth", "Django + django-allauth"], "notes": "Use httpOnly secure cookies, CSRF protection, rate limits, generic failure messages, and server-side session checks.", "requirements": ["server-side credential verification", "Argon2id/bcrypt password checks", "rate limiting and audit logging", "CSRF and secure-cookie configuration", "integration tests for invalid, locked, and verified users"], "env": ["AUTH_SECRET", "DATABASE_URL"], "files": {"login.tsx": "export function LoginForm() { return <form action=\"/api/auth/login\" method=\"post\" autoComplete=\"on\"><input name=\"email\" type=\"email\" autoComplete=\"email\" required /><input name=\"password\" type=\"password\" autoComplete=\"current-password\" required /><button type=\"submit\">Sign in</button></form>; }\n"}},
    "auth_signup": {"kind": "auth", "stacks": ["Next.js + Auth.js", "React + Clerk", "Django + django-allauth"], "notes": "Validate email ownership, hash passwords with Argon2id/bcrypt, prevent enumeration, require verification, and make account creation transactional.", "requirements": ["server-side schema validation", "unique-email constraint", "password strength and breached-password policy", "verification and abuse limits", "transactional rollback test"], "env": ["AUTH_SECRET", "DATABASE_URL", "EMAIL_FROM"], "files": {"signup.tsx": "export function SignupForm() { return <form action=\"/api/auth/signup\" method=\"post\" autoComplete=\"on\"><input name=\"email\" type=\"email\" autoComplete=\"email\" required /><input name=\"password\" type=\"password\" autoComplete=\"new-password\" minLength={12} required /><button type=\"submit\">Create account</button></form>; }\n"}},
    "payments_stripe": {"kind": "payments", "stacks": ["Next.js + Stripe Checkout", "Node.js + Stripe SDK", "Django + stripe-python"], "notes": "Create Checkout Sessions server-side, validate price IDs against your catalog, verify webhook signatures, make fulfillment idempotent, and never expose secret keys.", "requirements": ["server-side authenticated customer lookup", "allowlisted price IDs", "raw-body webhook verification", "idempotent fulfillment and refund handling", "test and live webhook separation"], "env": ["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"], "files": {"checkout.ts": "import Stripe from 'stripe';\nconst secret = process.env.STRIPE_SECRET_KEY;\nif (!secret) throw new Error('STRIPE_SECRET_KEY is required');\nconst stripe = new Stripe(secret);\nconst ALLOWED_PRICES = new Set((process.env.STRIPE_PRICE_IDS ?? '').split(',').filter(Boolean));\nexport async function createCheckout(priceId: string, successUrl: string, cancelUrl: string) {\n  if (!ALLOWED_PRICES.has(priceId)) throw new Error('Unsupported price');\n  return stripe.checkout.sessions.create({ mode: 'payment', line_items: [{ price: priceId, quantity: 1 }], success_url: successUrl, cancel_url: cancelUrl });\n}\n"}},
    "auth_password_reset": {"kind": "auth", "stacks": ["Next.js + Auth.js", "Supabase Auth", "Django + django-allauth"], "notes": "Use single-use, expiring tokens; return the same response for known and unknown emails; never log reset tokens.", "files": {"reset-request.ts": "export async function requestPasswordReset(email: string) { return fetch('/api/auth/reset', { method: 'POST', body: JSON.stringify({ email }), headers: { 'content-type': 'application/json' } }); }\n"}},
    "auth_oauth": {"kind": "auth", "stacks": ["Next.js + Auth.js", "React + Clerk", "Django OAuth Toolkit"], "notes": "Use Authorization Code + PKCE, validate state and nonce, restrict redirect URIs, and map provider identity to a stable internal user.", "files": {"oauth-notes.md": "Configure the provider callback on the server. Never accept an arbitrary redirect_uri from the browser.\n"}},
    "auth_email_verification": {"kind": "auth", "stacks": ["Supabase Auth", "Clerk", "Django + django-allauth"], "notes": "Require a signed, expiring verification token and enforce verified status at authorization boundaries.", "files": {"verification-notes.md": "Send verification mail through a transactional provider and make the confirmation endpoint idempotent.\n"}},
    "payments_subscription": {"kind": "payments", "stacks": ["Next.js + Stripe Billing", "Node.js + Stripe SDK", "Django + dj-stripe"], "notes": "Treat webhooks as the source of truth, persist subscription state, verify signatures, and handle cancellation, retries, and proration explicitly.", "files": {"subscription.ts": "export type SubscriptionState = 'active' | 'trialing' | 'past_due' | 'canceled';\nexport function canUsePaidFeature(state: SubscriptionState) { return state === 'active' || state === 'trialing'; }\n"}},
    "payments_paypal": {"kind": "payments", "stacks": ["Next.js + PayPal REST SDK", "Node.js + PayPal Checkout", "Django + PayPal REST"], "notes": "Create and capture orders server-side, validate the returned order with PayPal, and make fulfillment idempotent.", "files": {"paypal-notes.md": "Keep client IDs public only where intended; keep client secrets server-side and verify capture status before fulfillment.\n"}},
    "webhook_receiver": {"kind": "backend", "stacks": ["Next.js Route Handler", "Express + TypeScript", "FastAPI"], "notes": "Verify signatures against the raw request body, reject stale/replayed events, acknowledge quickly, and process idempotently.", "files": {"webhook-notes.md": "Persist event IDs before side effects so provider retries cannot duplicate work.\n"}},
    "profile_settings": {"kind": "ui", "stacks": ["Next.js + React Hook Form", "React + TanStack Form", "Django templates"], "notes": "Validate on the server, authorize field updates per user, and avoid returning sensitive profile fields.", "files": {"settings.tsx": "export function ProfileSettings() { return <form method=\"post\"><label>Display name<input name=\"displayName\" /></label><button type=\"submit\">Save changes</button></form>; }\n"}},
    "web3_wallet": {"kind": "web3", "stacks": ["Next.js + wagmi/viem", "React + ethers", "Svelte + viem"], "notes": "Treat wallet addresses as untrusted input, require chain-id checks, never expose private keys, and handle rejected/signature errors explicitly.", "requirements": ["allowlisted chains and RPC endpoints", "wallet/network mismatch handling", "server-side authorization for sensitive actions", "CSP and phishing-resistant domain checks", "tests for rejected and wrong-chain wallets"], "env": ["RPC_URL", "NEXT_PUBLIC_CHAIN_ID"], "files": {"wallet-notes.md": "Connect wallets in the browser, but verify chain ID and ownership on the server before granting access.\n"}},
    "web3_sign_in": {"kind": "web3", "stacks": ["Next.js + Sign-In with Ethereum", "FastAPI + eth-account", "Node.js + viem"], "notes": "Use a nonce-bound SIWE message with expiration, domain, URI, and chain ID; verify the signature server-side and rotate sessions.", "requirements": ["single-use nonce storage", "EIP-4361 message validation", "replay protection and expiry", "secure httpOnly session cookie", "tests for altered domain, nonce, and chain"], "env": ["SIWE_SESSION_SECRET"], "files": {"siwe-notes.md": "Never treat a wallet address alone as proof of ownership; require a verified, nonce-bound signature.\n"}},
    "web3_token_transfer": {"kind": "web3", "stacks": ["Next.js + viem", "Node.js + ethers", "Django + web3.py"], "notes": "Use allowlisted contract addresses and token decimals, simulate transactions before signing, and require explicit user confirmation.", "requirements": ["contract and chain allowlists", "simulation and gas-limit safeguards", "idempotent transaction tracking", "confirmation and receipt verification", "no private keys in frontend or logs"], "env": ["RPC_URL", "TOKEN_CONTRACT_ADDRESS", "SERVER_SIGNER_KEY"], "files": {"transfer-notes.md": "Construct and simulate transactions server-side; never accept arbitrary contract or recipient data without validation.\n"}},
}


def infer_block_name(prompt: str) -> str:
    text = prompt.lower()
    if re.search(r"\b(?:crypto|web3|blockchain)\b", text) and re.search(r"\bwallet\b", text):
        return "web3_wallet"
    if re.search(r"\b(?:sign\s*in|login)\b", text):
        return "auth_login"
    if re.search(r"\b(?:sign\s*up|signup|register)\b", text):
        return "auth_signup"
    if re.search(r"\b(?:stripe|checkout|payment)\b", text):
        return "payments_stripe"
    if re.search(r"\bsubscription\b", text):
        return "payments_subscription"
    if re.search(r"\bwebhook\b", text):
        return "webhook_receiver"
    return "profile_settings"


def block_slug(prompt: str, fallback: str) -> str:
    text = re.sub(r"(?i)\b(?:create|build|make|generate|save|as|block|component|page|starter)\b", " ", prompt)
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return text or fallback


def default_block_out(prompt: str, block_name: str) -> str:
    slug = block_slug(prompt, block_name)
    return f"blocks/{slug}.md"


def create_block(prompt: str, *, stack: str = "", out: str = "", force: bool = False) -> Path:
    block_name = infer_block_name(prompt)
    target = Path(out or default_block_out(prompt, block_name)).expanduser()
    if target.exists() and not force:
        raise FileExistsError(f"refusing to overwrite existing file: {target}; use --force")
    target.parent.mkdir(parents=True, exist_ok=True)
    text = render(block_name, stack)
    text += "\n\n## Source prompt\n\n"
    text += prompt.strip() + "\n"
    text += "\n## Reuse instructions\n\n"
    text += "Use this as a reusable Arka block spec. Adapt styling and framework details to the target project, but keep the production-readiness gates unless the user explicitly removes them.\n"
    target.write_text(text + "\n", encoding="utf-8")
    return target


def route_command(cmd: str) -> str | None:
    if not re.search(r"(?i)\b(?:create|build|make|generate)\b", cmd):
        return None
    if not re.search(r"(?i)\b(?:save|store|turn)\b.*\bblocks?\b|\bblocks?\b.*\b(?:save|store)\b", cmd):
        return None
    if not re.search(r"(?i)\b(?:page|component|starter|ui|block|wallet|login|payment|webhook|subscription)\b", cmd):
        return None
    return "blocks create " + shlex.quote(cmd)


def render(name: str, stack: str = "") -> str:
    block = BLOCKS[name]
    if stack and stack not in block["stacks"]:
        raise ValueError(f"unsupported stack for {name}: {stack}")
    selected = stack or block["stacks"][0]
    lines = [f"# Arka block: {name}", f"\nRecommended stack: {selected}", "\nSupported stack options:", *[f"- {item}" for item in block["stacks"]], f"\nSecurity/implementation notes: {block['notes']}", "\nRequired environment variables:", *[f"- `{item}`" for item in block.get("env", [])], "\nProduction readiness gates:", *[f"- [ ] {item}" for item in block.get("requirements", [])], "\nDo not ship until every gate is implemented and tested.", "\n## Files"]
    for filename, content in block["files"].items():
        lines += [f"\n### {filename}\n```tsx\n{content}```"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka blocks")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    show = sub.add_parser("show")
    show.add_argument("name", choices=sorted(BLOCKS))
    create = sub.add_parser("create")
    create.add_argument("prompt", nargs="+")
    create.add_argument("--stack", default="")
    create.add_argument("--out", default="")
    create.add_argument("--force", action="store_true")
    use = sub.add_parser("use")
    use.add_argument("name", choices=sorted(BLOCKS))
    use.add_argument("--stack", default="")
    use.add_argument("--out", required=True)
    use.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "list":
        for name, block in BLOCKS.items():
            print(f"{name}\t{block['kind']}\t{', '.join(block['stacks'])}")
        return 0
    if args.command == "show":
        print(json.dumps({"name": args.name, **BLOCKS[args.name]}, indent=2))
        return 0
    if args.command == "create":
        try:
            target = create_block(" ".join(args.prompt), stack=args.stack, out=args.out, force=args.force)
        except (FileExistsError, ValueError) as exc:
            parser.error(str(exc))
        print(f"created {target}")
        return 0
    target = Path(args.out).expanduser()
    if target.exists() and not args.force:
        parser.error(f"refusing to overwrite existing file: {target}; use --force")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(args.name, args.stack) + "\n", encoding="utf-8")
    print(f"created {target}")
    return 0
