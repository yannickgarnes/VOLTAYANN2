import os
import sys
import json
import time
import re
import traceback
import logging
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException, WebDriverException

# ============================================================
# CONFIGURACIÓN — LEE SIEMPRE DE VARIABLES DE ENTORNO
# ============================================================
URL = "https://www.bet365.es/#/IP/B1"
GSHEET_ID = os.getenv("GSHEET_ID", "1460RmnOhlkLFRG1uS3YzDQGotmkR8HspNmMQ2ABGaQA")

# En local puede usar el fichero JSON directamente (ruta en env var CREDS_JSON_PATH)
# En la nube usa el contenido JSON en la variable GSHEET_CREDENTIALS_JSON
CREDS_JSON_PATH = os.getenv("CREDS_JSON_PATH", "")
CREDS_JSON_CONTENT = os.getenv("GSHEET_CREDENTIALS_JSON", "")

# Detectar si estamos en Linux (nube) o Windows (local)
IS_CLOUD = sys.platform.startswith("linux")

# Directorio de logs: siempre relativo al script
BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = BASE_DIR / "volta_bot_debug.log"

# ============================================================
# LOGGING — Escribe a consola y a fichero
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_PATH), encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ============================================================
# ESTADO GLOBAL
# ============================================================
partidos_monitoreados = {}

# ============================================================
# GOOGLE SHEETS — Conexión resiliente con retry
# ============================================================
def _get_gsheet_client():
    """Devuelve un cliente gspread autenticado."""
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive",
    ]

    if CREDS_JSON_CONTENT:
        # NUBE: las credenciales están en la variable de entorno como string JSON
        creds_dict = json.loads(CREDS_JSON_CONTENT)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    elif CREDS_JSON_PATH and os.path.exists(CREDS_JSON_PATH):
        # LOCAL: ruta al fichero .json
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_JSON_PATH, scope)
    else:
        raise FileNotFoundError(
            "❌ No se encontraron credenciales de Google. "
            "Define GSHEET_CREDENTIALS_JSON (nube) o CREDS_JSON_PATH (local)."
        )

    return gspread.authorize(creds)


def guardar_en_gsheet(datos_fila, ambos_1p, ambos_partido, reintentos=3):
    """Sube fila a Google Sheets y pinta colores. Reintenta hasta 3 veces."""
    for intento in range(1, reintentos + 1):
        try:
            client = _get_gsheet_client()
            sheet = client.open_by_key(GSHEET_ID).sheet1

            nueva_fila = [
                datos_fila["eq1"], datos_fila["eq2"],
                datos_fila["g1p1"], datos_fila["g1p2"],
                datos_fila["g2p1"], datos_fila["g2p2"],
                f"{datos_fila['g1p1']+datos_fila['g2p1']}-{datos_fila['g1p2']+datos_fila['g2p2']}",
                "",  # H: CUOTA AMBOS MARCAN 1 PARTE
                "",  # I: AMBOS MARCAN
            ]
            sheet.append_row(nueva_fila)

            # Nº de fila real (más ligero que get_all_values)
            last_row = len(sheet.col_values(1))

            color_verde = {"red": 0.0, "green": 0.78, "blue": 0.0}
            color_rojo  = {"red": 0.9,  "green": 0.0,  "blue": 0.0}

            sheet.format(f"H{last_row}", {"backgroundColor": color_verde if ambos_1p    else color_rojo})
            sheet.format(f"I{last_row}", {"backgroundColor": color_verde if ambos_partido else color_rojo})

            logger.info(
                f"📊 [GSHEETS] ✅ Guardado: {datos_fila['eq1']} vs {datos_fila['eq2']} | "
                f"1P={datos_fila['g1p1']}-{datos_fila['g1p2']} | "
                f"2P={datos_fila['g2p1']}-{datos_fila['g2p2']}"
            )
            return  # Éxito, salir

        except Exception as e:
            logger.warning(f"⚠️ [GSHEETS] Intento {intento}/{reintentos} fallido: {e}")
            if intento < reintentos:
                time.sleep(5 * intento)  # Espera exponencial

    logger.error(f"❌ [GSHEETS] No se pudo guardar tras {reintentos} intentos.")


def guardar_resultado(datos):
    """Extrae nombres limpios y llama a guardar_en_gsheet."""
    try:
        m1 = re.search(r"\((.*?)\)", datos["eq1"])
        eq1 = m1.group(1).strip().upper() if m1 else datos["eq1"].strip().upper()
        m2 = re.search(r"\((.*?)\)", datos["eq2"])
        eq2 = m2.group(1).strip().upper() if m2 else datos["eq2"].strip().upper()

        datos_limpios = datos.copy()
        datos_limpios["eq1"], datos_limpios["eq2"] = eq1, eq2

        total_1 = datos["g1p1"] + datos["g2p1"]
        total_2 = datos["g1p2"] + datos["g2p2"]

        ambos_1p      = datos["g1p1"] > 0 and datos["g1p2"] > 0
        ambos_partido = total_1 > 0 and total_2 > 0

        logger.info(f"🏁 Guardando: {eq1} vs {eq2} | Final {total_1}-{total_2}")
        guardar_en_gsheet(datos_limpios, ambos_1p, ambos_partido)

    except Exception as e:
        logger.error(f"❌ Error en guardar_resultado: {e}")
        traceback.print_exc()


# ============================================================
# SELENIUM — Configuración del navegador (local + nube)
# ============================================================
def crear_driver():
    """Crea el driver de Chrome optimizado para local y cloud."""
    opts = Options()

    if IS_CLOUD:
        # ── MODO NUBE (Linux headless) ──────────────────────────
        logger.info("☁️  Modo NUBE detectado. Iniciando Chrome headless...")
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument("--disable-extensions")
        opts.add_argument("--proxy-server='direct://'")
        opts.add_argument("--proxy-bypass-list=*")
        # Spoofear User-Agent para no parecer bot
        opts.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36"
        )
        # Desactivar detección de automatización
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)

        # Chromium en Debian/Docker
        opts.binary_location = "/usr/bin/chromium"
        from selenium.webdriver.chrome.service import Service as ChromeService
        service = ChromeService(executable_path="/usr/bin/chromedriver")
        driver = webdriver.Chrome(service=service, options=opts)

    else:
        # ── MODO LOCAL (Windows con undetected-chromedriver) ────
        logger.info("🖥️  Modo LOCAL detectado. Iniciando Chrome con undetected-chromedriver...")
        import undetected_chromedriver as uc
        uc_opts = uc.ChromeOptions()
        uc_opts.add_argument("--start-maximized")
        uc_opts.add_argument("--disable-gpu")
        uc_opts.add_argument("--no-sandbox")
        uc_opts.add_argument("--disable-dev-shm-usage")
        driver = uc.Chrome(options=uc_opts)

    # Ejecutar script para ocultar navigator.webdriver
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"}
    )
    return driver


# ============================================================
# LÓGICA PRINCIPAL DEL BOT
# ============================================================
def ejecutar_bot():
    logger.info("=" * 60)
    logger.info("🚀 VOLTA BOT 24/7 — INICIANDO SISTEMA DE VIGILANCIA")
    logger.info(f"   Plataforma : {'☁️  NUBE (Linux)' if IS_CLOUD else '🖥️  LOCAL (Windows)'}")
    logger.info(f"   Google Sheet ID: {GSHEET_ID}")
    logger.info("=" * 60)

    while True:
        driver = None
        try:
            driver = crear_driver()
            wait = WebDriverWait(driver, 20)
            session_start = datetime.now()

            driver.get(URL)
            logger.info("🌐 Accediendo a Bet365...")
            time.sleep(14)

            # Aceptar cookies si aparece
            try:
                btn = driver.find_element(By.XPATH, "//div[contains(text(),'Aceptar') or contains(text(),'Accept')]")
                btn.click()
                logger.info("🍪 Cookies aceptadas.")
                time.sleep(2)
            except:
                pass

            fail_count   = 0
            session_mins = 50  # Reiniciar navegador cada 50 min

            # ── BUCLE PRINCIPAL DE ESCANEO ──────────────────────
            while True:
                elapsed = datetime.now() - session_start
                if elapsed > timedelta(minutes=session_mins):
                    logger.info(f"⏳ Sesión de {session_mins} min agotada. Reiniciando navegador para limpiar memoria...")
                    break

                try:
                    # Redirigir si nos saca de la página
                    if URL not in driver.current_url:
                        logger.warning("⚠️ URL inesperada. Volviendo a Bet365...")
                        driver.get(URL)
                        time.sleep(6)
                        continue

                    # ── BUSCAR SECCIÓN BATTLE VOLTA ─────────────
                    comp_elements = driver.find_elements(By.CLASS_NAME, "ovm-Competition")
                    volta_section = None
                    for comp in comp_elements:
                        try:
                            if "Battle Volta" in comp.text:
                                volta_section = comp
                                break
                        except StaleElementReferenceException:
                            continue

                    en_pantalla = set()

                    if volta_section:
                        fail_count = 0
                        try:
                            fixtures = volta_section.find_elements(By.CLASS_NAME, "ovm-Fixture")
                        except:
                            fixtures = []

                        for fixture in fixtures:
                            try:
                                # ── Nombres ────────────────────────────────────────
                                names = fixture.find_elements(By.CLASS_NAME, "ovm-FixtureDetailsTwoWay_TeamName")
                                if len(names) < 2:
                                    continue
                                eq_raw1 = names[0].text.strip()
                                eq_raw2 = names[1].text.strip()
                                if not eq_raw1 or not eq_raw2:
                                    continue

                                id_match = f"{eq_raw1} vs {eq_raw2}"
                                en_pantalla.add(id_match)

                                # ── Marcador ───────────────────────────────────────
                                s1 = int(fixture.find_element(By.CLASS_NAME, "ovm-StandardScoresSoccer_TeamOne").text.strip())
                                s2 = int(fixture.find_element(By.CLASS_NAME, "ovm-StandardScoresSoccer_TeamTwo").text.strip())

                                # ── Timer ──────────────────────────────────────────
                                timer_str = fixture.find_element(By.CLASS_NAME, "ovm-FixtureDetailsTwoWay_Timer").text.strip()
                                t_match   = re.search(r"(\d{2}):(\d{2})", timer_str)
                                minutos   = int(t_match.group(1)) if t_match else 0
                                segundos  = int(t_match.group(2)) if t_match else 0

                                # ── Registro nuevo partido ─────────────────────────
                                if id_match not in partidos_monitoreados:
                                    logger.info(f"🆕 DETECTADO: {id_match} | Tiempo: {timer_str} | Marcador: {s1}-{s2}")
                                    partidos_monitoreados[id_match] = {
                                        "eq1": eq_raw1, "eq2": eq_raw2,
                                        "estado": "jugando_1p",
                                        "g1p1": 0, "g1p2": 0,
                                        "g2p1": 0, "g2p2": 0,
                                        "ultimo_s1_visto": s1, "ultimo_s2_visto": s2,
                                        "marcador_pre_3min": (s1, s2),
                                        "ultimo_min": minutos,
                                        "detectado_at": datetime.now(),
                                    }

                                p = partidos_monitoreados[id_match]
                                p["ultimo_s1_visto"] = s1
                                p["ultimo_s2_visto"] = s2
                                p["ultimo_min"]       = minutos

                                # Guardar marcador antes del descanso
                                if minutos < 3:
                                    p["marcador_pre_3min"] = (s1, s2)

                                # ── MEDIA PARTE ────────────────────────────────────
                                if p["estado"] == "jugando_1p":
                                    ht_exacto      = "Descanso" in timer_str or "HT" in timer_str or (minutos == 3 and segundos <= 15)
                                    ht_recuperado  = minutos > 3

                                    if ht_exacto:
                                        logger.info(f"🌘 MEDIA PARTE: {id_match} → {s1}-{s2} (captura exacta)")
                                        p.update({"g1p1": s1, "g1p2": s2, "estado": "jugando_2p"})

                                    elif ht_recuperado:
                                        g1p, g2p = p["marcador_pre_3min"]
                                        logger.info(f"🌘 MEDIA PARTE: {id_match} → {g1p}-{g2p} (recuperado de buffer)")
                                        p.update({"g1p1": g1p, "g1p2": g2p, "estado": "jugando_2p"})

                                # ── FINAL ──────────────────────────────────────────
                                elif p["estado"] == "jugando_2p":
                                    ft = minutos >= 6 or "Finalizado" in timer_str or "FT" in timer_str
                                    if ft:
                                        goles_2p_1 = s1 - p["g1p1"]
                                        goles_2p_2 = s2 - p["g1p2"]
                                        logger.info(
                                            f"🏁 PARTIDO FINALIZADO: {id_match} | "
                                            f"1P: {p['g1p1']}-{p['g1p2']} | "
                                            f"2P: {goles_2p_1}-{goles_2p_2} | "
                                            f"Total: {s1}-{s2}"
                                        )
                                        p.update({"g2p1": goles_2p_1, "g2p2": goles_2p_2, "estado": "finalizado"})
                                        guardar_resultado(p)

                            except StaleElementReferenceException:
                                continue
                            except Exception as e_row:
                                logger.debug(f"  ⚠️ Error en fila: {e_row}")
                                continue

                    else:
                        fail_count += 1
                        logger.debug(f"  📡 Volta no visible ({fail_count}/15)...")
                        if fail_count > 15:
                            logger.info("  📡 Scroll de rescate para refrescar la vista...")
                            driver.execute_script("window.scrollBy(0, 400); setTimeout(() => window.scrollTo(0,0), 500);")
                            fail_count = 0

                    # ── RESCATE DE PARTIDOS DESAPARECIDOS ────────
                    borrar_lista = []
                    for mid, p in list(partidos_monitoreados.items()):
                        if mid not in en_pantalla and p["estado"] not in ["finalizado", "ignorado"]:
                            if p["estado"] == "jugando_2p" or p["ultimo_min"] >= 5:
                                logger.info(
                                    f"📡 RESCATE: '{mid}' desapareció en min {p['ultimo_min']}. "
                                    f"Último marcador: {p['ultimo_s1_visto']}-{p['ultimo_s2_visto']}"
                                )
                                p.update({
                                    "g2p1":    p["ultimo_s1_visto"] - p["g1p1"],
                                    "g2p2":    p["ultimo_s2_visto"] - p["g1p2"],
                                    "estado":  "finalizado",
                                })
                                guardar_resultado(p)
                            borrar_lista.append(mid)

                        elif p["estado"] == "finalizado":
                            # Limpiar partidos muy antiguos (>1h)
                            if (datetime.now() - p.get("detectado_at", datetime.now())).total_seconds() > 3600:
                                borrar_lista.append(mid)

                    for m in borrar_lista:
                        partidos_monitoreados.pop(m, None)

                    # ── ANTI-IDLE: pequeño movimiento ─────────────
                    if int(time.time()) % 90 < 5:
                        driver.execute_script("window.scrollBy(0,1);window.scrollBy(0,-1);")

                    time.sleep(4)

                except WebDriverException as e_driver:
                    logger.error(f"💀 WebDriverException: {e_driver}")
                    break  # Forzar reinicio del navegador

                except Exception as e_inner:
                    logger.error(f"⚠️ Error en bucle interno: {e_inner}")
                    if "stale" in str(e_inner).lower():
                        driver.get(URL)
                        time.sleep(5)
                    time.sleep(5)

        except Exception as e_outer:
            logger.error(f"❌ FALLO CRÍTICO EN SESIÓN: {e_outer}")
            traceback.print_exc()
            time.sleep(15)

        finally:
            if driver:
                try:
                    driver.quit()
                    logger.info("🔒 Navegador cerrado correctamente.")
                except:
                    pass
            logger.info("🔁 Reiniciando nueva sesión en 10 segundos...")
            time.sleep(10)


if __name__ == "__main__":
    ejecutar_bot()
