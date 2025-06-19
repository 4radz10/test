import discord
from discord import app_commands
import random
import string
from datetime import datetime, timedelta, timezone
import json
import os
import aiohttp
from aiohttp import web
import asyncio
import io

# === CONFIGURATION ===
BOT_TOKEN = "MTM4NTE1NjY3MTMwMjUzMzIxMQ.G-wBUJ.CTnOHew048pFGyhESbEDl-v3QRHFoshNTPyX8Q" 
TRANSCRIPT_WEBHOOK_URL = "https://discord.com/api/webhooks/1385157036702044171/ev9I310j_aniBJhheeXH06MMNtI6ieUcy86F2XYN2Qs4sIol6Xa3HUOAOsDEBIGNMYi2"
LICENSE_FILE = "licenses.json"
HTTP_SERVER_HOST = '0.0.0.0'
HTTP_SERVER_PORT = 5000
BOT_AVATAR_URL = "https://i.imgur.com/8GQY5qP.png" 
APP_NAME = "Cheats" 
LIFETIME_DAYS_REPR = 9999

# === BOT SETUP ===
intents = discord.Intents.default()
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)
licenses: dict[str, dict] = {}


# --- UTILITY FUNCTIONS ---
def generate_license_key(length: int = 16,
                         prefix: str = "KEY-") -> str: 
    chars = string.ascii_uppercase + string.digits
    random_part = ''.join(
        random.choice(chars) for _ in range(length - len(prefix)))
    return f"{prefix}{random_part}"


def format_expiry_for_display(expiry_dt: datetime | None) -> str:
    if expiry_dt is None: return "🌟 Lifetime Access (Never Expires!)"
    if expiry_dt.tzinfo is None:
        expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
    now_utc = datetime.now(timezone.utc)
    if expiry_dt < now_utc:
        return f"💔 Expired on {expiry_dt.strftime('%B %d, %Y')}"
    time_left = expiry_dt - now_utc
    days, hours, minutes = time_left.days, time_left.seconds // 3600, (
        time_left.seconds // 60) % 60
    if days >= 365 * 2:
        return "✨ Valid for a very long time!"
    if days > 0:
        return f"✅ Valid until {expiry_dt.strftime('%B %d, %Y')} ({days}d {hours}h left)"
    if hours > 0: return f"⏳ Expires soon! ({hours}h {minutes}m left)"
    return f"🚨 Expires in minutes! ({minutes}m left)"


def format_duration_command_display(days: int | None) -> str:
    if days == 0 or days is None: return "🌟 Lifetime"
    return f"⏳ {days} day{'s' if days != 1 else ''}"


async def send_log_to_webhook(embed: discord.Embed):
    if not TRANSCRIPT_WEBHOOK_URL or TRANSCRIPT_WEBHOOK_URL == "YOUR_WEBHOOK_URL":
        return
    async with aiohttp.ClientSession() as session:
        try:
            webhook = discord.Webhook.from_url(TRANSCRIPT_WEBHOOK_URL,
                                               session=session)
            await webhook.send(embed=embed,
                               username=f"{APP_NAME} Audit Logs",
                               avatar_url=BOT_AVATAR_URL)
        except Exception as e:
            print(f"[!] Webhook send failed: {e}")


def save_licenses_to_file():
    """Saves the current license dictionary to a plain-text JSON file."""
    try:
        data_to_save = {
            k: {
                "expiry":
                v['expiry'].isoformat() if v['expiry'] else "LIFETIME",
                "hwid": v.get('hwid'),
                "note": v.get('note'),
                "buyer_info": v.get('buyer_info')
            }
            for k, v in licenses.items()
        }
        with open(LICENSE_FILE, "w", encoding='utf-8') as f:
            json.dump(data_to_save, f, indent=2)
        print(
            f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] Licenses saved."
        )
    except Exception as e:
        print(f"[!] Save licenses failed: {e}")


def load_licenses_from_file():
    """Loads licenses from a plain-text JSON file."""
    global licenses
    if not os.path.exists(LICENSE_FILE):
        licenses = {}
        return
    try:
        with open(LICENSE_FILE, "r", encoding='utf-8') as f:
            content = f.read()
            if not content:  # Handle empty file
                licenses = {}
                return
            loaded_data = json.loads(content)

        temp_licenses = {}
        for k, v_data in loaded_data.items():
            exp_str = v_data.get("expiry")
            exp_dt = None if exp_str == "LIFETIME" else datetime.fromisoformat(
                exp_str) if exp_str else None
            temp_licenses[k] = {
                'expiry': exp_dt,
                'hwid': v_data.get('hwid'),
                'note': v_data.get('note'),
                'buyer_info': v_data.get('buyer_info')
            }
        licenses = temp_licenses
        print(f"[+] {len(licenses)} licenses loaded.")
    except json.JSONDecodeError:
        print(
            f"[!] Load licenses failed: '{LICENSE_FILE}' contains invalid JSON."
        )
        licenses = {}
    except Exception as e:
        print(f"[!] Load licenses failed: {e}")
        licenses = {}


# === HTTP SERVER ===
async def handle_license_check_http(request: web.Request):
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({
            'success': False,
            'message': 'Invalid JSON.'
        },
                                 status=400)

    key, client_hwid = data.get('key'), data.get('hwid')
    if not (isinstance(key, str) and isinstance(client_hwid, str) and key
            and client_hwid):
        return web.json_response({
            'success': False,
            'message': 'Bad key/HWID.'
        },
                                 status=400)

    key_upper = key.strip().upper()
    lic_data = licenses.get(key_upper)

    # Generic failure response template for keys that don't exist
    failure_response = {
        'success': False,
        'username': "N/A",
        'expires_in': 0,
        'exact_days_left': 0,
        'exact_hours_left': 0,
        'exact_minutes_left': 0
    }

    if not lic_data:
        failure_response['message'] = 'Not found.'
        return web.json_response(failure_response, status=404)

    stored_hwid, expiry_dt = lic_data.get('hwid'), lic_data.get('expiry')

    if stored_hwid is None:
        # First time use, lock HWID
        licenses[key_upper]['hwid'] = client_hwid
        save_licenses_to_file()
    elif stored_hwid != client_hwid:
        failure_response['message'] = 'HWID fail.'
        return web.json_response(failure_response, status=403)

    now_utc = datetime.now(timezone.utc)


    if expiry_dt is None:
        return web.json_response({
            'success': True,
            'message': 'Lifetime.',
            'username': f"{APP_NAME} User",
            'expires_in': LIFETIME_DAYS_REPR,
            'exact_days_left': LIFETIME_DAYS_REPR,
            'exact_hours_left': 0,
            'exact_minutes_left': 0
        })


    if expiry_dt.tzinfo is None:
        expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)


    if expiry_dt < now_utc:
        return web.json_response(
            {
                'success': False,
                'message': 'Expired.',
                'username': f"{APP_NAME} User",
                'expires_in': 0,
                'exact_days_left': 0,
                'exact_hours_left': 0,
                'exact_minutes_left': 0
            },
            status=403)


    time_left = expiry_dt - now_utc
    days_left = time_left.days

    seconds_in_day = time_left.seconds
    hours_left = seconds_in_day // 3600
    minutes_left = (seconds_in_day // 60) % 60

    return web.json_response({
        'success': True,
        'message': 'Valid.',
        'username': f"{APP_NAME} User",
        'expires_in': days_left, 
        'exact_days_left': days_left,
        'exact_hours_left': hours_left,
        'exact_minutes_left': minutes_left,
    })


async def start_http_api_server(app: web.Application):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HTTP_SERVER_HOST, HTTP_SERVER_PORT)
    try:
        await site.start()
        print(f"[+] HTTP API on {HTTP_SERVER_HOST}:{HTTP_SERVER_PORT}")
        while True:
            await asyncio.sleep(3600)
    except Exception as e:
        print(f"[!!!] HTTP server error: {e}")



@bot.event
async def on_ready():
    load_licenses_from_file()
    try:
        print(f"✅ Synced {len(await tree.sync())} slash commands.")
    except Exception as e:
        print(f"[!] Command sync failed: {e}")
    print(f"✅ Bot '{bot.user.name}' is sparkling and ready!")
    http_app = web.Application()
    http_app.router.add_post('/check_license', handle_license_check_http)
    bot.loop.create_task(start_http_api_server(http_app))



COLOR_SUCCESS = discord.Color.from_rgb(255, 193, 7)
COLOR_ERROR = discord.Color.from_rgb(255, 87, 34)
COLOR_INFO = discord.Color.from_rgb(255, 152, 0)
COLOR_GENERAL = discord.Color.from_rgb(255, 204, 128)


def create_bot_embed(title: str,
                     description: str = "",
                     color: discord.Color = COLOR_GENERAL) -> discord.Embed:
    embed = discord.Embed(title=f"🔑 {APP_NAME} License Portal",
                          description=title,
                          color=color,
                          timestamp=datetime.now(timezone.utc))
    if description:
        embed.add_field(name="📝 Details", value=description, inline=False)
    embed.set_footer(text=f"Your trusted license manager | {bot.user.name}",
                     icon_url=BOT_AVATAR_URL)
    return embed


def create_success_bot_embed(operation: str, details: str) -> discord.Embed:
    embed = discord.Embed(title=f"🎉 Success! {operation}",
                          description=details,
                          color=COLOR_SUCCESS,
                          timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=f"{APP_NAME} | {bot.user.name}",
                     icon_url=BOT_AVATAR_URL)
    return embed


def create_error_bot_embed(operation: str, reason: str) -> discord.Embed:
    embed = discord.Embed(title=f"⚠️ Uh oh! {operation}",
                          description=reason,
                          color=COLOR_ERROR,
                          timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=f"{APP_NAME} | {bot.user.name}",
                     icon_url=BOT_AVATAR_URL)
    return embed


def create_info_bot_embed(title: str, details: str) -> discord.Embed:
    embed = discord.Embed(title=f"💡 Heads Up! {title}",
                          description=details,
                          color=COLOR_INFO,
                          timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=f"{APP_NAME} | {bot.user.name}",
                     icon_url=BOT_AVATAR_URL)
    return embed


def create_log_embed(
    action: str,
    performed_by: discord.User,
    color: discord.Color = discord.Color.dark_orange()
) -> discord.Embed:
    embed = discord.Embed(title=f"📜 Audit Log: {action}",
                          color=color,
                          timestamp=datetime.now(timezone.utc))
    embed.set_author(
        name=f"Action by: {performed_by.display_name} ({performed_by.id})",
        icon_url=performed_by.display_avatar.url)
    embed.set_footer(text=f"{bot.user.name} Secure Logging",
                     icon_url=BOT_AVATAR_URL)
    return embed


license_admin_cmds = app_commands.Group(
    name="license", description=f"Manage {APP_NAME} licenses.")


@license_admin_cmds.command(
    name="create", description=f"✨ Create a new license key for {APP_NAME}.")
@app_commands.describe(
    duration_days=f"How many days it lasts (0 for lifetime magic ✨).",
    owner_id="Optional: Who is this key for? (e.g., Discord ID, email)",
    memo="Optional: Any special notes for this key?")
@app_commands.checks.has_permissions(administrator=True)
async def license_create_cmd(interaction: discord.Interaction,
                             duration_days: int,
                             owner_id: str = None,
                             memo: str = None):
    if duration_days < 0:
        await interaction.response.send_message(embed=create_error_bot_embed(
            "Key Creation Error",
            "Duration must be positive or 0 for lifetime."),
                                                ephemeral=True)
        return
    expiry_dt = None if duration_days == 0 else datetime.now(
        timezone.utc) + timedelta(days=duration_days)
    new_key = generate_license_key()
    licenses[new_key] = {
        'expiry': expiry_dt,
        'hwid': None,
        'note': memo,
        'buyer_info': owner_id
    }
    save_licenses_to_file()

    user_embed = discord.Embed(
        title="🎁 Your New License Key is Here!",
        description=
        f"Congratulations! You've received a license for **{APP_NAME}**.\n**Important:** Store this key safely!",
        color=COLOR_SUCCESS,
        timestamp=datetime.now(timezone.utc))
    user_embed.add_field(name="🔑 Your Key",
                         value=f"```{new_key}```",
                         inline=False)
    user_embed.add_field(name="🪔 Validity",
                         value=format_duration_command_display(duration_days),
                         inline=True)
    user_embed.add_field(name="🗓️ Expires",
                         value=format_expiry_for_display(expiry_dt),
                         inline=True)
    if owner_id:
        user_embed.add_field(name="👤 For", value=owner_id, inline=False)
    if memo:
        user_embed.add_field(name="📝 Admin Memo", value=memo, inline=False)
    user_embed.set_footer(text=f"Enjoy {APP_NAME}!", icon_url=BOT_AVATAR_URL)
    await interaction.response.send_message(embed=user_embed, ephemeral=False)

    log = create_log_embed("New Key Generated", interaction.user,
                           COLOR_SUCCESS)
    log.add_field(name="Key", value=f"`{new_key}`")
    await send_log_to_webhook(log)


@license_admin_cmds.command(
    name="status", description="🔍 Check the current status of a license key.")
@app_commands.describe(license_key="The license key you'd like to inspect.")
@app_commands.checks.has_permissions(administrator=True)
async def license_status_cmd(interaction: discord.Interaction,
                             license_key: str):
    key_upper = license_key.strip().upper()
    lic_data = licenses.get(key_upper)
    if not lic_data:
        await interaction.response.send_message(embed=create_error_bot_embed(
            "Key Not Found",
            f"Hmm, I couldn't find a license with the key `{key_upper}`."),
                                                ephemeral=True)
        return
    embed = create_info_bot_embed(f"🔍 Status for License: `{key_upper}`", "")
    embed.add_field(name="Current Validity",
                    value=format_expiry_for_display(lic_data['expiry']),
                    inline=False)
    embed.add_field(name="💻 Device Lock (HWID)",
                    value=f"`{lic_data['hwid']}`" if lic_data['hwid'] else
                    "🔓 Not locked to a specific device.",
                    inline=True)
    if lic_data.get('buyer_info'):
        embed.add_field(name="👤 Registered To",
                        value=lic_data['buyer_info'],
                        inline=True)
    if lic_data.get('note'):
        embed.add_field(name="📝 Admin Memo",
                        value=lic_data['note'],
                        inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@license_admin_cmds.command(
    name="remove", description="🗑️ Permanently remove (revoke) a license key.")
@app_commands.describe(
    license_key="The license key to delete from the system.")
@app_commands.checks.has_permissions(administrator=True)
async def license_remove_cmd(interaction: discord.Interaction,
                             license_key: str):
    key_upper = license_key.strip().upper()
    if key_upper not in licenses:
        await interaction.response.send_message(embed=create_error_bot_embed(
            "Removal Failed", f"Key `{key_upper}` doesn't exist to remove."),
                                                ephemeral=True)
        return
    licenses.pop(key_upper)
    save_licenses_to_file()
    await interaction.response.send_message(embed=create_success_bot_embed(
        "Key Removed",
        f"The license `{key_upper}` has been successfully deleted."),
                                            ephemeral=True)
    log = create_log_embed("Key Removed", interaction.user, COLOR_ERROR)
    log.add_field(name="Key", value=f"`{key_upper}`")
    await send_log_to_webhook(log)


@license_admin_cmds.command(name="listall",
                            description="📜 View all licenses (paginated).")
@app_commands.describe(page="Which page of the license list to display.")
@app_commands.checks.has_permissions(administrator=True)
async def license_listall_cmd(interaction: discord.Interaction, page: int = 1):
    if not licenses:
        await interaction.response.send_message(embed=create_info_bot_embed(
            "License List Empty", "No licenses found in the system yet!"),
                                                ephemeral=True)
        return
    items_pp, lic_items = 5, sorted(list(licenses.items()), key=lambda i: i[0])
    total_pg = (len(lic_items) + items_pp - 1) // items_pp
    page = max(1, min(page, total_pg))
    start, end = (page - 1) * items_pp, page * items_pp
    pg_items = lic_items[start:end]
    embed = create_bot_embed(
        f"📜 {APP_NAME} License Roster - Page {page}/{total_pg}",
        f"Showing {len(pg_items)} of {len(lic_items)} total licenses.",
        COLOR_INFO)
    if not pg_items:
        embed.description = "No licenses on this page."
    else:
        for k, d in pg_items:
            val = f"**Validity:** {format_expiry_for_display(d['expiry'])}\n**Device Lock:** `{d['hwid']}`" if d[
                'hwid'] else "🔓 Unlocked"
            if d.get('buyer_info'): val += f"\n**Owner:** {d['buyer_info']}"
            if d.get('note'): val += f"\n**Memo:** *{d.get('note')}*"
            embed.add_field(name=f"🔑 `{k}`", value=val, inline=False)
            if len(embed) > 5800:
                embed.remove_field(-1)
                embed.add_field(name="...",
                                value="List truncated (size limit).",
                                inline=False)
                break
    if len(str(embed.to_dict())) > 5900:
        txt = "\n".join([
            f"Key: {k}\n Status: {format_expiry_for_display(d['expiry'])}\n HWID: {d.get('hwid', 'None')}\n Owner: {d.get('buyer_info', 'N/A')}\n Memo: {d.get('note', 'N/A')}\n"
            for k, d in lic_items
        ])
        await interaction.response.send_message(
            "List too long for an embed, sending as a file:",
            file=discord.File(io.BytesIO(txt.encode('utf-8')),
                              "all_licenses.txt"),
            ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="ping",
              description="🏓 Check if the bot is feeling responsive!")
async def ping_cmd(interaction: discord.Interaction):
    latency_ms = round(bot.latency * 1000, 1)
    embed = create_success_bot_embed(
        "I'm Here!",
        f"Pong! 🎉 My connection speed is a swift **{latency_ms}ms**.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


tree.add_command(license_admin_cmds)


async def on_license_admin_cmd_error(interaction: discord.Interaction,
                                     error: app_commands.AppCommandError):
    op_name = interaction.command.name.replace(
        "_", " ").title() if interaction.command else "Operation"
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(embed=create_error_bot_embed(
            f"{op_name} Access Denied",
            "Sorry, you need Administrator powers for this!"),
                                                ephemeral=True)
    elif isinstance(error, app_commands.CommandInvokeError):
        print(
            f"[!!!] Error in '{interaction.command.qualified_name if interaction.command else 'N/A'}': {error.original}"
        )
        await interaction.response.send_message(embed=create_error_bot_embed(
            f"{op_name} Failed",
            "Something went sideways. I've noted the issue for my creators!"),
                                                ephemeral=True)
    else:
        print(
            f"[!] Unhandled error for '{interaction.command.qualified_name if interaction.command else 'N/A'}': {error}"
        )
        if not interaction.response.is_done():
            await interaction.response.send_message(
                embed=create_error_bot_embed(
                    "Error",
                    f"An odd glitch occurred: {type(error).__name__}."),
                ephemeral=True)


for command in license_admin_cmds.commands:
    command.error(on_license_admin_cmd_error)


if __name__ == "__main__":
    if not BOT_TOKEN or "YOUR_BOT_TOKEN_HERE" in BOT_TOKEN:
        print(
            "[!!!] BOT_TOKEN is missing. Please set it correctly in the script!"
        )
        exit(1)
    if APP_NAME == "Your App Name":
        print(
            f"[!] Reminder: Please customize 'APP_NAME' in the script! (Currently: {APP_NAME})"
        )
    if not os.path.exists(LICENSE_FILE):
        print(f"[*] '{LICENSE_FILE}' not found, creating empty file.")
        with open(LICENSE_FILE, 'w') as f:
            f.write('{}')
    bot.run(BOT_TOKEN)
