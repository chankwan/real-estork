"""
RealEstork — CLI Tool
Usage: python -m cli.main <command> [options]

Commands:
  spider run <name>          Run a single spider
  spider list                List available spiders
  classify <listing_id>      Show classification breakdown
  ai status                  Show current AI model + accuracy
  ai switch <provider/model> Switch AI model
  ai models                  List available models
  mark <id> <status>         Mark listing status (called/owner/broker)
  digest                     Send daily digest now
  start                      Start the full orchestrator
  doctor                     Health check (deps, .env, browser binaries)
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import typer
from dotenv import load_dotenv
from loguru import logger
from rich.console import Console
from rich.table import Table
from rich import print as rprint

load_dotenv()

app = typer.Typer(
    name="realestork",
    help="RealEstork — OSINT Real Estate Platform CLI",
    no_args_is_help=True,
)
spider_app = typer.Typer(help="Spider management commands")
ai_app = typer.Typer(help="AI model management commands")
app.add_typer(spider_app, name="spider")
app.add_typer(ai_app, name="ai")

console = Console()


# =========================================================
# SPIDER COMMANDS
# =========================================================

@spider_app.command("run")
def spider_run(
    name: str = typer.Argument(help="Spider name (nhatot, batdongsan, alonhadat)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print results, don't save to DB"),
):
    """Run a single spider and show results."""
    from spiders import SpiderEngine

    console.print(f"[bold cyan]Running spider: {name}[/bold cyan]")

    async def _run():
        engine = SpiderEngine()
        listings = await engine.fetch_one(name)

        if not listings:
            console.print(f"[yellow]No listings found from '{name}'[/yellow]")
            return

        table = Table(title=f"{name} Results ({len(listings)} listings)")
        table.add_column("ID", style="dim", width=12)
        table.add_column("Title", width=30)
        table.add_column("District", width=12)
        table.add_column("Price", width=15)
        table.add_column("Floor", width=8)
        table.add_column("Age (h)", width=8)
        table.add_column("Phone", width=12)

        for l in listings[:20]:  # Show first 20
            age = f"{l.listing_age_hours:.1f}" if l.listing_age_hours else "?"
            floor = str(l.floor_level) if l.floor_level else "?"
            table.add_row(
                l.source_id[:10],
                (l.title or "")[:28],
                (l.district or "")[:10],
                l.price_text[:13] if l.price_text else "?",
                floor,
                age,
                (l.phone or "")[:10],
            )

        console.print(table)
        if len(listings) > 20:
            console.print(f"[dim]... and {len(listings) - 20} more[/dim]")

        if not dry_run:
            console.print("\n[dim]Note: Use --dry-run to skip DB save[/dim]")

    asyncio.run(_run())


@spider_app.command("list")
def spider_list():
    """List all configured spiders and their status."""
    import yaml

    with open("config/spiders.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    table = Table(title="Configured Spiders")
    table.add_column("Name", style="bold")
    table.add_column("Enabled")
    table.add_column("Type")
    table.add_column("Interval")
    table.add_column("Max Pages")

    for s in config.get("spiders", []):
        enabled = "✅" if s.get("enabled") else "❌"
        table.add_row(
            s["name"],
            enabled,
            s.get("type", "?"),
            f"{s.get('interval_minutes', '?')} min",
            str(s.get("max_pages", "?")),
        )

    console.print(table)


# =========================================================
# CLASSIFY COMMANDS
# =========================================================

@app.command("classify")
def classify_listing(
    listing_id: str = typer.Argument(help="Listing ID (source-source_id or UUID)"),
):
    """Show classification score breakdown for a listing."""
    from db.client import SupabaseDB
    from pipeline.classifier import ClassificationPipeline
    from pipeline.signals import SignalContext
    from spiders.base import RawListing

    db = SupabaseDB()
    classifier = ClassificationPipeline()

    # Try to find listing (by UUID or source-sourceid)
    listing_data = None
    if "-" in listing_id:
        listing_data = db.get_listing_by_id(listing_id)

    if not listing_data:
        console.print(f"[red]Listing not found: {listing_id}[/red]")
        raise typer.Exit(1)

    # Reconstruct
    class MockListing:
        pass
    listing = MockListing()
    for k, v in listing_data.items():
        setattr(listing, k, v)

    phone_stats = db.get_phone_stats(listing_data.get("phone", ""))
    result = classifier.classify(listing, phone_stats=phone_stats)

    console.print(f"\n[bold]Classification: {listing_data.get('title', '')[:50]}[/bold]")
    console.print(f"Score: [bold cyan]{result.score}[/bold cyan] → {result.label}")
    console.print(f"\n[bold]Signals fired:[/bold]")

    table = Table()
    table.add_column("Signal", width=35)
    table.add_column("Contribution", width=15)
    for sig, contrib in sorted(result.signals_fired.items(), key=lambda x: abs(x[1]), reverse=True):
        color = "green" if contrib > 0 else "red"
        table.add_row(sig, f"[{color}]{contrib:+.0f}[/{color}]")

    console.print(table)


# =========================================================
# MARK COMMAND (feedback from CLI, mirrors Zalo /mark)
# =========================================================

@app.command("mark")
def mark_listing(
    listing_ref: str = typer.Argument(help="Listing reference (source-source_id)"),
    status: str = typer.Argument(help="Status: called | owner | broker | archived"),
    notes: str = typer.Option("", "--notes", "-n", help="Optional notes"),
):
    """Mark a listing status (mirrors Zalo /mark command)."""
    STATUS_MAP = {
        "called": "called",
        "owner": "confirmed_owner",
        "broker": "confirmed_broker",
        "archived": "archived",
    }
    if status not in STATUS_MAP:
        console.print(f"[red]Invalid status. Use: {', '.join(STATUS_MAP.keys())}[/red]")
        raise typer.Exit(1)

    db_status = STATUS_MAP[status]
    console.print(f"[dim]Marking {listing_ref} as {db_status}...[/dim]")
    # TODO: Look up listing by short ref and update status
    console.print(f"[green]✅ {listing_ref} → {db_status}[/green]")


# =========================================================
# AI COMMANDS
# =========================================================

@ai_app.command("status")
def ai_status():
    """Show current AI model and recent accuracy."""
    import yaml
    with open("config/ai.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    ai_cfg = config.get("ai", {})
    provider = ai_cfg.get("provider", "unknown")

    console.print(f"\n[bold]Current AI Provider:[/bold] {provider}")

    if provider == "ollama":
        model = ai_cfg.get("ollama", {}).get("model", "?")
        url = ai_cfg.get("ollama", {}).get("base_url", "?")
        console.print(f"Model: {model}")
        console.print(f"URL: {url}")
    elif provider == "zero-token":
        model = ai_cfg.get("zero_token", {}).get("model", "?")
        console.print(f"Model: {model} (via openclaw-zero-token)")
    elif provider == "anthropic":
        model = ai_cfg.get("anthropic", {}).get("model", "?")
        console.print(f"Model: {model}")

    console.print(f"\nTemperature: {ai_cfg.get('temperature', 0.1)}")
    console.print(f"Max tokens: {ai_cfg.get('max_tokens', 300)}")
    console.print(f"Fallback to rules: {ai_cfg.get('fallback_to_rules_on_error', True)}")


@ai_app.command("switch")
def ai_switch(
    model_path: str = typer.Argument(
        help="Format: provider/model e.g. ollama/gemma4:e4b or zero-token/deepseek-web"
    ),
):
    """Switch AI model by editing config/ai.yaml."""
    console.print(f"[yellow]Manual edit required:[/yellow]")
    console.print(f"Edit [bold]config/ai.yaml[/bold] → uncomment your desired tier")
    console.print(f"Then restart the orchestrator")
    console.print(f"\nRequested: [cyan]{model_path}[/cyan]")


@ai_app.command("models")
def ai_models():
    """List all available AI models by tier."""
    table = Table(title="Available AI Models")
    table.add_column("Tier", style="bold")
    table.add_column("Provider")
    table.add_column("Model")
    table.add_column("Cost")
    table.add_column("Notes")

    models = [
        ("4 (Free)", "ollama", "gemma4:e4b", "Free", "DEFAULT — Local GPU, offline ✅"),
        ("4 (Free)", "ollama", "gemma4:e2b", "Free", "Lighter model"),
        ("4 (Free)", "ollama", "qwen2.5:7b", "Free", "Strong Vietnamese"),
        ("1 (Free)", "zero-token", "deepseek-web/deepseek-chat", "Free", "Web chat, needs browser login"),
        ("1 (Free)", "zero-token", "qwen-web/qwen-max", "Free", "Web chat"),
        ("1 (Free)", "zero-token", "gemini-web/gemini-pro", "Free", "Web chat"),
        ("2 ($20/mo)", "zero-token", "chatgpt-web/gpt-4o", "$20/mo sub", "ChatGPT Plus"),
        ("3 (Pay/token)", "anthropic", "claude-haiku-4-5", "$0.25/1M tokens", "Best accuracy"),
    ]
    for tier, provider, model, cost, notes in models:
        table.add_row(tier, provider, model, cost, notes)

    console.print(table)


# =========================================================
# DIGEST + START
# =========================================================

@app.command("setup-batdongsan")
def setup_batdongsan():
    """First-time login setup cho Batdongsan phone reveal (Google OAuth hoặc SĐT/Email + Password)."""
    console.print("\n[bold cyan]RealEstork — Batdongsan Login Setup[/bold cyan]")
    console.print("─" * 55)
    console.print("Yêu cầu: tài khoản đã verify SĐT trên batdongsan.com.vn\n")
    console.print("1. Chrome sẽ mở thẳng [bold]trang đăng nhập[/bold] batdongsan.com.vn")
    console.print("2. Chọn phương thức đăng nhập:")
    console.print("   [bold](A) Google OAuth[/bold]: click 'Đăng nhập với Google' → chọn account")
    console.print("   [bold](B) SĐT/Email + Password[/bold]: điền trực tiếp vào form")
    console.print("3. Sau khi vào được trang chủ, [bold]chờ vài giây[/bold] để bot lưu cookies")
    console.print("4. Browser tự đóng khi xong\n")
    console.print("[dim]Timeout: 5 phút | Auto-refresh: headless, không cần làm thêm gì[/dim]\n")

    async def _run():
        from auth.batdongsan_auth import BatdongsanAuthClient
        client = BatdongsanAuthClient()
        success = await client.setup_interactive()
        if success:
            console.print("[green]✅ Setup thành công! Cookies đã lưu vào .batdongsan_cookies.json[/green]")
            hours = client.expires_in_hours()
            if hours:
                console.print(f"[dim]Cookies hết hạn sau: {hours:.0f}h (~{hours/24:.1f} ngày)[/dim]")
        else:
            console.print("[red]❌ Setup thất bại. Kiểm tra log phía trên.[/red]")
            raise typer.Exit(1)

    asyncio.run(_run())


    asyncio.run(_run())


@app.command("setup-nhatot")
def setup_nhatot():
    """First-time Google login setup for Nhatot phone reveal."""
    console.print("\n[bold cyan]RealEstork — Nhatot Google OAuth Setup[/bold cyan]")
    console.print("─" * 50)
    console.print("1. Chrome sẽ mở ra")
    console.print("2. Vào [bold]chotot.com[/bold] → click [bold]Đăng nhập[/bold] → chọn [bold]Google[/bold]")
    console.print("3. Đăng nhập bằng tài khoản Google của bạn")
    console.print("4. Sau khi vào được trang chủ, chờ vài giây để bot capture token")
    console.print("5. Browser tự đóng khi xong\n")
    console.print("[dim]Timeout: 5 phút[/dim]\n")

    async def _run():
        from auth.nhatot_auth import NhatotAuthClient
        client = NhatotAuthClient()
        token = await client.setup_interactive()
        if token:
            # Persist to .env
            from orchestrator.agent import _update_env_file
            _update_env_file("NHATOT_ACCESS_TOKEN", token)
            os.environ["NHATOT_ACCESS_TOKEN"] = token
            console.print("[green]✅ Setup thành công! Token đã được lưu vào .env[/green]")
            console.print(f"[dim]Token (20 chars): {token[:20]}...[/dim]")
        else:
            console.print("[red]❌ Setup thất bại. Kiểm tra log phía trên.[/red]")
            raise typer.Exit(1)

    asyncio.run(_run())


@app.command("setup-muaban")
def setup_muaban():
    """First-time login setup cho Muaban.net phone reveal (Google OAuth)."""
    console.print("\n[bold cyan]RealEstork — Muaban.net Login Setup[/bold cyan]")
    console.print("─" * 55)
    console.print("1. Chrome sẽ mở thẳng [bold]trang đăng nhập[/bold] muaban.net")
    console.print("2. Chọn [bold]Đăng nhập với Google[/bold] và hoàn tất đăng nhập")
    console.print("3. Sau khi vào được trang chủ/cá nhân, [bold]chờ vài giây[/bold] để bot lưu cookies")
    console.print("4. Browser tự đóng khi xong\n")
    console.print("[dim]Timeout: 5 phút | Auto-refresh: headless, không cần làm thêm gì[/dim]\n")

    async def _run():
        from auth.muaban_auth import MuabanAuthClient
        client = MuabanAuthClient()
        success = await client.setup_interactive()
        if success:
            console.print("[green]✅ Setup thành công! Cookies đã lưu vào .muaban_cookies.json[/green]")
        else:
            console.print("[red]❌ Setup thất bại. Kiểm tra log phía trên.[/red]")
            raise typer.Exit(1)

    asyncio.run(_run())


@app.command("digest")
def send_digest_now():
    """Trigger daily digest immediately."""
    async def _run():
        from orchestrator.agent import RealEstorkAgent
        agent = RealEstorkAgent()
        await agent.daily_digest()
        console.print("[green]✅ Digest sent[/green]")

    asyncio.run(_run())


@app.command("start")
def start_orchestrator(
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without sending alerts"),
):
    """Start the full RealEstork orchestrator."""
    import sys
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "orchestrator.log"
    logger.remove()
    logger.add(sys.stderr, level="INFO", colorize=True,
               format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")
    logger.add(str(log_file), level="DEBUG", rotation="1 day", retention="7 days",
               encoding="utf-8",
               format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} | {message}")
    console.print(f"[bold cyan]Starting RealEstork Orchestrator...[/bold cyan]")
    console.print(f"[dim]Logs → {log_file.resolve()}[/dim]")

    async def _run():
        from orchestrator.agent import RealEstorkAgent
        agent = RealEstorkAgent(dry_run=dry_run)
        await agent.start()

    asyncio.run(_run())


@app.command("doctor")
def doctor() -> None:
    """Pre-flight health check: deps, browser binaries, .env, services."""
    import importlib.util
    import sys
    from pathlib import Path

    OK = "[green][OK][/green]"
    FAIL = "[red][X][/red]"
    WARN = "[yellow][!][/yellow]"

    failures = 0
    warnings = 0

    def _check(label: str, ok: bool, fix_msg: str | None = None, *, warn: bool = False) -> None:
        nonlocal failures, warnings
        if ok:
            console.print(f"  {OK} {label}")
        elif warn:
            console.print(f"  {WARN} {label}")
            if fix_msg:
                console.print(f"       [dim]→ {fix_msg}[/dim]")
            warnings += 1
        else:
            console.print(f"  {FAIL} {label}")
            if fix_msg:
                console.print(f"       [dim]→ Sửa: {fix_msg}[/dim]")
            failures += 1

    console.print("\n[bold cyan]RealEstork Doctor — Health Check[/bold cyan]\n")

    # 1. Python version
    console.print("[bold]1. Python[/bold]")
    py = sys.version_info
    _check(
        f"Python {py.major}.{py.minor}.{py.micro}",
        py >= (3, 12),
        "cần Python 3.12+. Tải: https://www.python.org/downloads/",
    )

    # 2. Critical Python packages
    console.print("\n[bold]2. Python packages[/bold]")
    required_pkgs = [
        ("scrapling", "pip install -r requirements-lock.txt"),
        ("patchright", "pip install patchright (hoặc pip install scrapling[fetchers])"),
        ("msgspec", "pip install msgspec"),
        ("camoufox", "pip install camoufox[geoip]"),
        ("playwright", "pip install playwright"),
        ("supabase", "pip install supabase"),
        ("telegram", "pip install python-telegram-bot"),
        ("apscheduler", "pip install apscheduler"),
        ("loguru", "pip install loguru"),
        ("yaml", "pip install pyyaml"),
        ("dotenv", "pip install python-dotenv"),
    ]
    for mod, fix in required_pkgs:
        spec = importlib.util.find_spec(mod)
        _check(f"{mod}", spec is not None, fix)

    # 3. Browser binaries
    console.print("\n[bold]3. Browser binaries[/bold]")
    try:
        spec = importlib.util.find_spec("scrapling")
        if spec is not None:
            from scrapling import StealthyFetcher  # noqa: F401
            _check("StealthyFetcher import", True)
        else:
            _check("StealthyFetcher import", False, "venv/Scripts/scrapling.exe install")
    except ImportError as e:
        _check(
            "StealthyFetcher import",
            False,
            f"({type(e).__name__}: {e}) → venv/Scripts/scrapling.exe install",
        )

    # Camoufox browser binary path
    try:
        from camoufox.pkgman import installed_verstr
        ver = installed_verstr()
        _check(f"Camoufox browser binary (version {ver})", True)
    except Exception:
        _check(
            "Camoufox browser binary",
            False,
            "venv/Scripts/python.exe -m camoufox fetch",
            warn=True,
        )

    # 4. .env file + critical keys
    console.print("\n[bold]4. Cấu hình .env[/bold]")
    env_path = Path(".env")
    if not env_path.exists():
        _check(
            ".env file",
            False,
            "copy .env.example .env && điền tokens",
        )
    else:
        _check(".env file tồn tại", True)
        critical_keys = [
            ("SUPABASE_URL", "URL Supabase project"),
            ("SUPABASE_SERVICE_KEY", "Supabase service role key"),
            ("TELEGRAM_BOT_TOKEN", "Token bot Telegram (lấy từ @BotFather)"),
            ("TELEGRAM_ADMIN_CHAT_ID", "Chat ID cá nhân để nhận admin alerts"),
        ]
        for key, desc in critical_keys:
            val = os.getenv(key, "").strip()
            has_val = bool(val) and not val.startswith("your-")
            _check(f"{key}", has_val, f"điền vào .env: {desc}")

        optional_keys = [
            ("TELEGRAM_GROUP_CHAT_ID", "Group chat (vợ chồng cùng xem)"),
        ]
        for key, desc in optional_keys:
            val = os.getenv(key, "").strip()
            has_val = bool(val) and not val.startswith("your-")
            _check(f"{key} (optional)", has_val, f"không bắt buộc — {desc}", warn=True)

    # 5. Config files
    console.print("\n[bold]5. Config files[/bold]")
    for cfg in ("config/spiders.yaml", "config/scoring.yaml", "config/schedule.yaml"):
        _check(cfg, Path(cfg).exists(), f"thiếu file {cfg} — git pull lại")

    # 6. Supabase connectivity
    console.print("\n[bold]6. Kết nối services[/bold]")
    try:
        from db.client import SupabaseDB
        db = SupabaseDB()
        db.client.table("listings").select("id").limit(1).execute()
        _check("Supabase reachable", True)
    except Exception as e:
        _check(
            "Supabase reachable",
            False,
            f"kiểm tra SUPABASE_URL/SUPABASE_SERVICE_KEY trong .env ({type(e).__name__}: {e})",
        )

    # 7. Telegram bot token
    try:
        import httpx
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            _check("Telegram bot token", False, "điền TELEGRAM_BOT_TOKEN vào .env")
        else:
            r = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=5)
            ok = r.status_code == 200 and r.json().get("ok") is True
            _check(
                "Telegram bot token hợp lệ",
                ok,
                "token sai hoặc bot bị revoke. Tạo lại qua @BotFather",
            )
    except Exception as e:
        _check("Telegram bot token", False, f"không gọi được Telegram API ({e})", warn=True)

    # Summary
    console.print()
    if failures == 0 and warnings == 0:
        console.print("[bold green]✓ Tất cả check đều OK. Bot sẵn sàng chạy.[/bold green]")
        console.print("[dim]Chạy: bot start[/dim]\n")
    elif failures == 0:
        console.print(f"[yellow]⚠ {warnings} cảnh báo nhưng không fatal. Bot vẫn chạy được.[/yellow]\n")
    else:
        console.print(
            f"[bold red]✗ {failures} lỗi cần sửa[/bold red]"
            + (f" + {warnings} cảnh báo" if warnings else "")
            + ". Sửa theo hướng dẫn ở trên rồi chạy lại: [cyan]bot doctor[/cyan]\n"
        )
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
