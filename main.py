"""
╔══════════════════════════════════════════════════════════╗
║ MARKET ORACLE BOT - by Tarzan                           ║
║ Precios en tiempo real + Analisis + Noticias            ║
╚══════════════════════════════════════════════════════════╝

COMANDOS:
/start - Bienvenida
/precio - Todos los precios ahora
/btc - Bitcoin detallado
/oro - Oro (XAU/USD) detallado
/forex - EUR/USD, USD/JPY, etc.
/analisis - Analisis tecnico (tendencia, RSI, soporte/resistencia)
/news - Ultimas noticias cripto y mercados
/alerta - Configurar alerta de precio personalizada
/stop - Detener alertas automaticas
/ayuda - Lista de comandos
"""

import os
import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

# CONFIGURACION

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8735148146:AAF40fEWA6iusZNRwRVc_AfnbqkgaePoU_E")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY", "6b011354c7944ffa816ca37f0337a768")
INTERVALO_HORAS = 4

# LOGGING

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# EMOJIS & HELPERS

def flecha(valor):
    return "📈" if valor >= 0 else "📉"

def color_pct(pct):
    if pct >= 2: return "🟢🔥"
    elif pct >= 0: return "🟢"
    elif pct >= -2: return "🔴"
    else: return "🔴💀"

def senal_tendencia(pct_7d):
    if pct_7d > 5: return "🚀 ALCISTA FUERTE"
    elif pct_7d > 1: return "📈 ALCISTA"
    elif pct_7d > -1: return "➡️ LATERAL"
    elif pct_7d > -5: return "📉 BAJISTA"
    else: return "💀 BAJISTA FUERTE"

def rsi_senal(rsi):
    if rsi is None: return "N/A"
    if rsi > 70: return f"{rsi:.0f} 🔴 SOBRECOMPRADO"
    elif rsi < 30: return f"{rsi:.0f} 🟢 SOBREVENDIDO"
    else: return f"{rsi:.0f} ⚪ NEUTRAL"

def resistencia_nota(pct_desde_max):
    if pct_desde_max < 2: return "⚡ MUY CERCA del maximo - posible ruptura"
    elif pct_desde_max < 5: return "👀 Cerca de resistencia - vigilar"
    elif pct_desde_max < 15: return "📊 Zona media - sin senal clara"
    else: return "🧱 Lejos de resistencia - espacio de subida"

# APIs DE DATOS

async def get_crypto_data():
    url = (
        "https://api.coingecko.com/api/v3/coins/markets"
        "?vs_currency=usd"
        "&ids=bitcoin,ethereum,solana,ripple"
        "&order=market_cap_desc"
        "&price_change_percentage=1h,24h,7d"
    )
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status == 200:
                return await r.json()
    return []

async def get_gold_data():
    url = "https://api.metals.live/v1/spot/gold,silver"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    data = await r.json()
                    gold = next((item.get("gold") for item in data if "gold" in item), None)
                    silver = next((item.get("silver") for item in data if "silver" in item), None)
                    return {"gold": gold, "silver": silver}
        except Exception as e:
            logger.warning(f"Error gold API: {e}")
    return {"gold": None, "silver": None}

async def get_forex_data():
    url = "https://api.frankfurter.app/latest?from=USD&to=EUR,GBP,JPY,CHF"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    return await r.json()
        except Exception as e:
            logger.warning(f"Error forex API: {e}")
    return {}

async def get_fear_greed():
    url = "https://api.alternative.me/fng/?limit=1"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    data = await r.json()
                    return data["data"][0]
        except Exception as e:
            logger.warning(f"Error F&G: {e}")
    return None

async def get_news():
    if NEWS_API_KEY == "PEGA_TU_NEWSAPI_KEY_AQUI":
        return None
    url = (
        f"https://newsapi.org/v2/everything"
        f"?q=bitcoin+OR+crypto+OR+gold+OR+inflation"
        f"&language=es"
        f"&sortBy=publishedAt"
        f"&pageSize=5"
        f"&apiKey={NEWS_API_KEY}"
    )
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    data = await r.json()
                    return data.get("articles", [])
        except Exception as e:
            logger.warning(f"Error news API: {e}")
    return []

async def get_news_english_fallback():
    url = "https://api.coingecko.com/api/v3/news?per_page=5"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    data = await r.json()
                    return data.get("data", [])
        except Exception as e:
            logger.warning(f"Error CG news: {e}")
    return []

# ANALISIS TECNICO SIMPLE

def calcular_rsi_simple(precio_actual, precio_7d):
    if precio_7d == 0:
        return 50
    cambio = (precio_actual - precio_7d) / precio_7d * 100
    rsi = 50 + cambio * 1.5
    return max(0, min(100, rsi))

def nivel_soporte_resistencia(precio, ath):
    magnitud = 10 ** (len(str(int(precio))) - 2)
    nivel_actual = int(precio / magnitud) * magnitud
    soporte = nivel_actual
    resistencia = nivel_actual + magnitud
    pct_desde_ath = ((ath - precio) / ath) * 100 if ath else None
    return soporte, resistencia, pct_desde_ath

# FORMATEADORES DE MENSAJES

async def formato_resumen_completo():
    crypto_data = await get_crypto_data()
    gold_data = await get_gold_data()
    forex_data = await get_forex_data()
    fg = await get_fear_greed()

    ahora = datetime.now().strftime("%d/%m/%Y %H:%M")
    msg = f"📊 *MARKET ORACLE* • {ahora[:5]}\n\n"

    msg += "━━━ 🔐 CRYPTO ━━━━━━━━━━━━\n"
    for coin in crypto_data:
        p1h = coin.get("price_change_percentage_1h_in_currency") or 0
        p24h = coin.get("price_change_percentage_24h_in_currency") or 0
        p7d = coin.get("price_change_percentage_7d_in_currency") or 0
        precio = coin["current_price"]
        simbolo = coin["symbol"].upper()
        nombre = coin["name"]

        msg += (
            f"\n{flecha(p24h)} *{nombre}* (${simbolo})\n"
            f" 💵 `${precio:,.2f}`\n"
            f" 1h: {color_pct(p1h)} {p1h:+.2f}% "
            f"24h: {color_pct(p24h)} {p24h:+.2f}% "
            f"7d: {color_pct(p7d)} {p7d:+.2f}%\n"
            f" {senal_tendencia(p7d)}\n"
        )

    msg += "\n━━━ 🥇 METALES ━━━━━━━━━━━\n"
    if gold_data["gold"]:
        msg += f"\n🥇 *Oro* (XAU/USD)\n 💵 `${gold_data['gold']:,.2f}` /oz\n"
    else:
        msg += "\n🥇 *Oro* — datos no disponibles\n"
    if gold_data["silver"]:
        msg += f"🥈 *Plata* (XAG/USD)\n 💵 `${gold_data['silver']:,.3f}` /oz\n"

    msg += "\n━━━ 💱 FOREX ━━━━━━━━━━━━━\n"
    if forex_data and "rates" in forex_data:
        rates = forex_data["rates"]
        eur = rates.get("EUR")
        gbp = rates.get("GBP")
        jpy = rates.get("JPY")
        if eur: msg += f" 🇪🇺 EUR/USD: `{eur:.4f}`\n"
        if gbp: msg += f" 🇬🇧 GBP/USD: `{gbp:.4f}`\n"
        if jpy: msg += f" 🇯🇵 USD/JPY: `{1/jpy*100:.2f}` (×100)\n"
    else:
        msg += " Datos forex no disponibles\n"

    if fg:
        valor = int(fg["value"])
        clasificacion = fg["value_classification"]
        emoji_fg = "😱" if valor < 25 else "😨" if valor < 45 else "😐" if valor < 55 else "😁" if valor < 75 else "🤑"
        msg += f"\n━━━ 🧠 SENTIMIENTO ━━━━━━━━\n"
        msg += f" {emoji_fg} Fear & Greed: *{valor}/100* — {clasificacion}\n"

    msg += f"\n_Proxima actualizacion en {INTERVALO_HORAS}h_ 🔄"
    return msg

async def formato_btc_detallado():
    crypto_data = await get_crypto_data()
    btc = next((c for c in crypto_data if c["id"] == "bitcoin"), None)
    if not btc:
        return "❌ No se pudieron obtener datos de BTC."

    precio = btc["current_price"]
    p24h = btc.get("price_change_percentage_24h_in_currency") or 0
    p7d = btc.get("price_change_percentage_7d_in_currency") or 0
    p1h = btc.get("price_change_percentage_1h_in_currency") or 0
    ath = btc.get("ath", 0)
    mcap = btc.get("market_cap", 0)
    vol = btc.get("total_volume", 0)
    max24 = btc.get("high_24h", precio)
    min24 = btc.get("low_24h", precio)

    precio_7d_est = precio / (1 + p7d/100) if p7d != -100 else precio
    rsi = calcular_rsi_simple(precio, precio_7d_est)
    soporte, resistencia, pct_ath = nivel_soporte_resistencia(precio, ath)
    pct_desde_ath = pct_ath if pct_ath else 0

    msg = f"₿ *BITCOIN — Analisis Completo*\n"
    msg += f"{'═'*30}\n\n"
    msg += f"💵 Precio: `${precio:,.2f}`\n"
    msg += f"📊 Cambio: 1h {p1h:+.2f}% | 24h {p24h:+.2f}% | 7d {p7d:+.2f}%\n\n"
    msg += f"📈 Max 24h: `${max24:,.2f}`\n"
    msg += f"📉 Min 24h: `${min24:,.2f}`\n"
    msg += f"🏆 ATH: `${ath:,.2f}` ({pct_desde_ath:.1f}% por debajo)\n\n"
    msg += f"💰 Market Cap: `${mcap/1e9:.1f}B`\n"
    msg += f"📦 Volumen 24h: `${vol/1e9:.1f}B`\n\n"
    msg += f"━━━ 📐 ANALISIS TECNICO ━━━━━━━━\n"
    msg += f"RSI (aprox): {rsi_senal(rsi)}\n"
    msg += f"Tendencia 7d: {senal_tendencia(p7d)}\n"
    msg += f"Soporte: ~`${soporte:,.0f}`\n"
    msg += f"Resistencia: ~`${resistencia:,.0f}`\n"
    msg += f"{resistencia_nota(pct_desde_ath)}\n\n"

    msg += "━━━ 💡 CONSEJO ━━━━━━━━━━━━━━━\n"
    if rsi > 70 and p7d > 10:
        msg += "⚠️ Mercado *sobrecomprado* — posible correccion. Cuidado con entrar ahora."
    elif rsi < 30 and p7d < -10:
        msg += "🎯 Zona de *posible acumulacion* — historicamente buen momento para DCA."
    elif p7d > 3:
        msg += "🟢 Tendencia positiva — mercado en momentum alcista."
    elif p7d < -3:
        msg += "🔴 Presion bajista — esperar confirmacion antes de entrar."
    else:
        msg += "➡️ Mercado lateral — paciencia, esperar movimiento claro."

    return msg

# HANDLERS DE COMANDOS

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 Ver precios", callback_data="precio"),
         InlineKeyboardButton("₿ Bitcoin", callback_data="btc")],
        [InlineKeyboardButton("🥇 Oro", callback_data="oro"),
         InlineKeyboardButton("📰 Noticias", callback_data="news")],
        [InlineKeyboardButton("📐 Analisis", callback_data="analisis"),
         InlineKeyboardButton("❓ Ayuda", callback_data="ayuda")],
    ]
    markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "💰 *MARKET ORACLE BOT*\n\n"
        "Tu asistente de mercados financieros 📈\n\n"
        "Cubro: *BTC, ETH, SOL, XRP, Oro, Plata, Forex*\n"
        f"📩 Alertas automaticas cada *{INTERVALO_HORAS} horas*\n\n"
        "Pulsa un boton o usa los comandos:",
        parse_mode="Markdown",
        reply_markup=markup
    )
    chat_id = update.effective_chat.id
    if not ctx.job_queue.get_jobs_by_name(str(chat_id)):
        ctx.job_queue.run_repeating(
            enviar_alerta_automatica,
            interval=INTERVALO_HORAS * 3600,
            first=10,
            chat_id=chat_id,
            name=str(chat_id)
        )

async def cmd_precio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg_obj = await update.message.reply_text("⏳ Obteniendo datos del mercado…")
    try:
        texto = await formato_resumen_completo()
        await msg_obj.edit_text(texto, parse_mode="Markdown")
    except Exception as e:
        await msg_obj.edit_text(f"❌ Error: {e}")

async def cmd_btc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg_obj = await update.message.reply_text("₿ Analizando Bitcoin…")
    try:
        texto = await formato_btc_detallado()
        await msg_obj.edit_text(texto, parse_mode="Markdown")
    except Exception as e:
        await msg_obj.edit_text(f"❌ Error: {e}")

async def cmd_oro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg_obj = await update.message.reply_text("🥇 Consultando precio del oro…")
    try:
        gold_data = await get_gold_data()
        if gold_data["gold"]:
            precio = gold_data["gold"]
            s = int(precio / 50) * 50
            r = s + 50
            pct = ((r - precio) / precio) * 100

            texto = (
                f"🥇 *ORO — XAU/USD*\n"
                f"{'═'*28}\n\n"
                f"💵 Precio actual: `${precio:,.2f}` /oz\n"
                f"📦 Equivalente 1kg: `${precio * 32.15:,.0f}`\n\n"
                f"━━━ 📐 ANALISIS ━━━━━━━━━━━━━\n"
                f"Soporte: ~`${s:,.0f}`\n"
                f"Resistencia: ~`${r:,.0f}`\n"
                f"Distancia a resistencia: {pct:.1f}%\n\n"
                f"━━━ 💡 CONTEXTO ━━━━━━━━━━━━━\n"
                f"El oro es refugio en incertidumbre.\n"
                f"Si el dolar sube -> oro baja.\n"
                f"Si hay tension geopolitica -> oro sube."
            )
            if gold_data["silver"]:
                ratio = precio / gold_data["silver"]
                texto += f"\n\n🥈 Plata: `${gold_data['silver']:.3f}`\n"
                texto += f"Ratio Oro/Plata: `{ratio:.0f}x`"
                if ratio > 80:
                    texto += " <- plata *barata* vs oro historicamente"
        else:
            texto = "❌ No se pudieron obtener datos del oro. Intenta en unos minutos."
        await msg_obj.edit_text(texto, parse_mode="Markdown")
    except Exception as e:
        await msg_obj.edit_text(f"❌ Error: {e}")

async def cmd_forex(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg_obj = await update.message.reply_text("💱 Consultando divisas…")
    try:
        forex = await get_forex_data()
        if forex and "rates" in forex:
            r = forex["rates"]
            eur = r.get("EUR", 0)
            gbp = r.get("GBP", 0)
            jpy = r.get("JPY", 0)
            chf = r.get("CHF", 0)

            texto = (
                f"💱 *FOREX — Tipos de cambio*\n"
                f"Base: 1 USD\n"
                f"{'═'*28}\n\n"
                f"🇪🇺 EUR/USD: `{eur:.4f}`\n"
                f"🇬🇧 GBP/USD: `{gbp:.4f}`\n"
                f"🇯🇵 USD/JPY: `{1/jpy*100:.2f}` (x100)\n"
                f"🇨🇭 USD/CHF: `{1/chf:.4f}`\n\n"
                f"_Fuente: Frankfurter.app | BCE_"
            )
        else:
            texto = "❌ Datos forex no disponibles ahora."
        await msg_obj.edit_text(texto, parse_mode="Markdown")
    except Exception as e:
        await msg_obj.edit_text(f"❌ Error: {e}")

async def cmd_analisis(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg_obj = await update.message.reply_text("📐 Calculando analisis tecnico…")
    try:
        crypto_data = await get_crypto_data()
        fg = await get_fear_greed()

        texto = "📐 *ANALISIS TECNICO DEL MERCADO*\n"
        texto += f"{'═'*30}\n\n"

        for coin in crypto_data[:3]:
            nombre = coin["name"]
            precio = coin["current_price"]
            p7d = coin.get("price_change_percentage_7d_in_currency") or 0
            p24h = coin.get("price_change_percentage_24h_in_currency") or 0
            ath = coin.get("ath", precio)

            precio_7d_est = precio / (1 + p7d/100) if p7d != -100 else precio
            rsi = calcular_rsi_simple(precio, precio_7d_est)
            soporte, resistencia, pct_ath = nivel_soporte_resistencia(precio, ath)

            texto += f"*{nombre}* — `${precio:,.2f}`\n"
            texto += f" RSI: {rsi_senal(rsi)}\n"
            texto += f" Tendencia: {senal_tendencia(p7d)}\n"
            texto += f" Soporte: ~`${soporte:,.0f}` | Res: ~`${resistencia:,.0f}`\n"
            if pct_ath is not None:
                texto += f" {resistencia_nota(pct_ath)}\n"
            texto += "\n"

        if fg:
            valor = int(fg["value"])
            texto += f"━━━ 🧠 SENTIMIENTO GENERAL ━━━━━\n"
            texto += f"Fear & Greed: *{valor}/100* — {fg['value_classification']}\n\n"
            if valor < 25:
                texto += "💡 Extremo miedo -> historicamente *buen momento para comprar*"
            elif valor > 75:
                texto += "⚠️ Extrema codicia -> mercado puede estar *sobreextendido*"
            else:
                texto += "📊 Sentimiento neutro — sin senal extrema"

        await msg_obj.edit_text(texto, parse_mode="Markdown")
    except Exception as e:
        await msg_obj.edit_text(f"❌ Error: {e}")

async def cmd_news(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg_obj = await update.message.reply_text("📰 Cargando noticias…")
    try:
        articulos = await get_news()

        if articulos is None:
            articulos_cg = await get_news_english_fallback()
            if articulos_cg:
                texto = "📰 *ULTIMAS NOTICIAS — Cripto*\n"
                texto += f"{'═'*30}\n\n"
                for art in articulos_cg[:5]:
                    titulo = art.get("title", "Sin titulo")[:80]
                    autor = art.get("author", "")
                    url = art.get("url", "")
                    texto += f"🔹 {titulo}\n"
                    if autor:
                        texto += f" _{autor}_\n"
                    if url:
                        texto += f" [Leer mas]({url})\n"
                    texto += "\n"
                texto += "\n💡 *Tip:* Añade tu NewsAPI key para noticias en español."
            else:
                texto = (
                    "📰 *Noticias*\n\n"
                    "Para noticias en español configura tu NewsAPI key:\n"
                    "1. Registrate gratis en newsapi.org\n"
                    "2. Añade la key como variable de entorno `NEWS_API_KEY`\n\n"
                    "Por ahora puedo darte analisis de mercado con /analisis 📐"
                )
        elif articulos:
            texto = "📰 *ULTIMAS NOTICIAS — Mercados*\n"
            texto += f"{'═'*30}\n\n"
            for art in articulos[:5]:
                titulo = art.get("title", "")[:80]
                fuente = art.get("source", {}).get("name", "")
                url = art.get("url", "")
                texto += f"🔹 *{titulo}*\n"
                if fuente:
                    texto += f" _{fuente}_\n"
                if url:
                    texto += f" [Leer mas]({url})\n"
                texto += "\n"
        else:
            texto = "❌ No se encontraron noticias en este momento."

        await msg_obj.edit_text(texto, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        await msg_obj.edit_text(f"❌ Error cargando noticias: {e}")

async def cmd_alerta(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if len(args) < 2:
        await update.message.reply_text(
            "📌 *Alertas de precio personalizadas*\n\n"
            "Uso: `/alerta [moneda] [precio]`\n\n"
            "Ejemplos:\n"
            "`/alerta btc 100000` — avisa si BTC supera $100k\n"
            "`/alerta eth 3000` — avisa si ETH supera $3k\n"
            "`/alerta gold 3500` — avisa si oro supera $3500\n",
            parse_mode="Markdown"
        )
        return

    moneda = args[0].lower()
    try:
        precio_objetivo = float(args[1].replace(",", ""))
    except ValueError:
        await update.message.reply_text("❌ Precio invalido. Usa numeros: `/alerta btc 95000`", parse_mode="Markdown")
        return

    chat_id = update.effective_chat.id
    nombre_job = f"alerta_{chat_id}_{moneda}_{precio_objetivo}"

    ctx.job_queue.run_repeating(
        check_alerta_precio,
        interval=600,
        first=10,
        chat_id=chat_id,
        name=nombre_job,
        data={"moneda": moneda, "objetivo": precio_objetivo, "nombre_job": nombre_job}
    )

    await update.message.reply_text(
        f"✅ *Alerta configurada*\n\n"
        f"Te avisare cuando *{moneda.upper()}* supere `${precio_objetivo:,.0f}`\n"
        f"Comprobando cada 10 minutos 🔔",
        parse_mode="Markdown"
    )

async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    jobs = ctx.job_queue.get_jobs_by_name(str(chat_id))
    if jobs:
        for job in jobs:
            job.schedule_removal()
        await update.message.reply_text("🔕 Alertas automaticas desactivadas.")
    else:
        await update.message.reply_text("No hay alertas activas.")

async def cmd_ayuda(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *COMANDOS DISPONIBLES*\n"
        f"{'═'*30}\n\n"
        "📊 `/precio` — Resumen de todos los mercados\n"
        "₿ `/btc` — Bitcoin con analisis tecnico\n"
        "🥇 `/oro` — Oro y plata (XAU, XAG)\n"
        "💱 `/forex` — EUR/USD, GBP, JPY, CHF\n"
        "📐 `/analisis` — RSI, tendencias, soportes\n"
        "📰 `/news` — Ultimas noticias del mercado\n"
        "🔔 `/alerta btc 95000` — Alerta de precio\n"
        "🔕 `/stop` — Desactivar alertas automaticas\n\n"
        f"📩 Resumen automatico cada *{INTERVALO_HORAS}h*\n\n"
        "⚠️ *Este bot es solo informativo. No es asesoramiento financiero.*",
        parse_mode="Markdown"
    )

# JOBS AUTOMATICOS

async def enviar_alerta_automatica(ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = ctx.job.chat_id
    try:
        texto = await formato_resumen_completo()
        await ctx.bot.send_message(
            chat_id=chat_id,
            text=f"🔔 *ACTUALIZACION AUTOMATICA*\n\n{texto}",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error alerta automatica: {e}")

async def check_alerta_precio(ctx: ContextTypes.DEFAULT_TYPE):
    data = ctx.job.data
    moneda = data["moneda"]
    objetivo = data["objetivo"]
    nombre_job = data["nombre_job"]
    chat_id = ctx.job.chat_id

    try:
        precio_actual = None
        if moneda in ["btc", "bitcoin"]:
            crypto_data = await get_crypto_data()
            btc = next((c for c in crypto_data if c["id"] == "bitcoin"), None)
            if btc:
                precio_actual = btc["current_price"]
        elif moneda in ["eth", "ethereum"]:
            crypto_data = await get_crypto_data()
            eth = next((c for c in crypto_data if c["id"] == "ethereum"), None)
            if eth:
                precio_actual = eth["current_price"]
        elif moneda in ["gold", "oro", "xau"]:
            gold_data = await get_gold_data()
            precio_actual = gold_data.get("gold")

        if precio_actual and precio_actual >= objetivo:
            await ctx.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🚨 *¡ALERTA ACTIVADA!*\n\n"
                    f"*{moneda.upper()}* ha alcanzado `${precio_actual:,.2f}`\n"
                    f"Tu objetivo era: `${objetivo:,.0f}`\n\n"
                    f"¡Es el momento que estabas esperando! 🎯"
                ),
                parse_mode="Markdown"
            )
            for job in ctx.job_queue.get_jobs_by_name(nombre_job):
                job.schedule_removal()
    except Exception as e:
        logger.error(f"Error check alerta: {e}")

# CALLBACK BOTONES INLINE

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    handlers = {
        "precio": cmd_precio,
        "btc": cmd_btc,
        "oro": cmd_oro,
        "news": cmd_news,
        "analisis": cmd_analisis,
        "ayuda": cmd_ayuda,
    }

    if data in handlers:
        update.message = query.message
        await handlers[data](update, ctx)

# MAIN

def main():
    if BOT_TOKEN == "PEGA_TU_TOKEN_AQUI":
        print("❌ ERROR: Configura BOT_TOKEN en las variables de entorno")
        return

    print("🚀 Iniciando Market Oracle Bot...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("precio", cmd_precio))
    app.add_handler(CommandHandler("btc", cmd_btc))
    app.add_handler(CommandHandler("oro", cmd_oro))
    app.add_handler(CommandHandler("forex", cmd_forex))
    app.add_handler(CommandHandler("analisis", cmd_analisis))
    app.add_handler(CommandHandler("news", cmd_news))
    app.add_handler(CommandHandler("alerta", cmd_alerta))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("ayuda", cmd_ayuda))

    app.add_handler(CallbackQueryHandler(callback_handler))

    print(f"✅ Bot activo — alertas automaticas cada {INTERVALO_HORAS}h")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
