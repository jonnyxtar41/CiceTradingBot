"""
Notificador Seguro, No Bloqueante e Interactivo para Telegram
Permite enviar alertas detalladas, fotos del gráfico de TradingView y recibir órdenes
en tiempo real a través de botones interactivos en tu móvil.
"""
import time
import json
import uuid
import threading
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional, Callable
from utils.logger import logger


class TelegramNotifier:
    """
    Envía notificaciones hacia Telegram y escucha respuestas interactivas mediante
    botones inline para permitir la confirmación manual de órdenes desde el móvil.
    """
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        self.enabled = bool(cfg.get("activo", False))
        self.token = str(cfg.get("token_bot", "")).strip()
        self.chat_id = str(cfg.get("chat_id", "")).strip()
        self.execution_mode = str(cfg.get("modo_ejecucion", "confirmacion")).lower()
        self.send_screenshots = bool(cfg.get("enviar_captura_pantalla", True))
        self.signal_expiry_seconds = int(cfg.get("expiracion_senal_segundos", 600))

        self.notify_signals = bool(cfg.get("notificar_senales", True))
        self.notify_executions = bool(cfg.get("notificar_ejecuciones", True))
        self.notify_closes = bool(cfg.get("notificar_cierres", True))
        self.timeout = 5

        # Gestión de señales interactivas
        self.pending_trades: Dict[str, dict] = {}
        self.on_trade_confirm_callback: Optional[Callable] = None
        self._listener_running = False
        self._listener_thread: Optional[threading.Thread] = None

        if self.enabled:
            if not self.token or not self.chat_id:
                logger.warning("⚠️ [Telegram] Notificaciones activadas pero falta 'token_bot' o 'chat_id' en config.yaml.")
                self.enabled = False
            else:
                logger.info(f"📱 [Telegram] Módulo activado | Modo: {self.execution_mode.upper()} | Capturas: {self.send_screenshots}")

    def send_message(self, message: str, inline_keyboard: list = None) -> bool:
        """Envía un mensaje de texto formateado en HTML vía API de Telegram"""
        if not self.enabled or not self.token or not self.chat_id:
            return False

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if inline_keyboard:
            payload["reply_markup"] = {"inline_keyboard": inline_keyboard}

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url, 
                data=data, 
                headers={"Content-Type": "application/json", "User-Agent": "ModularTradingBot/1.0"}
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return response.status == 200
        except Exception as e:
            logger.warning(f"⚠️ [Telegram] No se pudo enviar mensaje ({type(e).__name__}): {e}")
            return False

    def send_photo(self, photo_bytes: bytes, caption: str, inline_keyboard: list = None) -> bool:
        """Envía una imagen (captura del gráfico) con texto y botones interactivos"""
        if not self.enabled or not self.token or not self.chat_id or not photo_bytes:
            return False

        url = f"https://api.telegram.org/bot{self.token}/sendPhoto"
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
        body = []
        body.append(f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{self.chat_id}\r\n'.encode('utf-8'))
        body.append(f'--{boundary}\r\nContent-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'.encode('utf-8'))
        body.append(f'--{boundary}\r\nContent-Disposition: form-data; name="parse_mode"\r\n\r\nHTML\r\n'.encode('utf-8'))
        if inline_keyboard:
            body.append(f'--{boundary}\r\nContent-Disposition: form-data; name="reply_markup"\r\n\r\n{json.dumps({"inline_keyboard": inline_keyboard})}\r\n'.encode('utf-8'))
        body.append(f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="chart.png"\r\nContent-Type: image/png\r\n\r\n'.encode('utf-8') + photo_bytes + b'\r\n')
        body.append(f'--{boundary}--\r\n'.encode('utf-8'))

        try:
            req = urllib.request.Request(
                url,
                data=b''.join(body),
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "User-Agent": "ModularTradingBot/1.0"}
            )
            with urllib.request.urlopen(req, timeout=12) as response:
                return response.status == 200
        except Exception as e:
            logger.warning(f"⚠️ [Telegram] No se pudo enviar foto ({type(e).__name__}): {e}")
            # Si falla la foto, intenta enviar como texto normal
            return self.send_message(caption, inline_keyboard)

    def answer_callback_query(self, callback_id: str, text: str = ""):
        """Confirma la pulsación de un botón mostrando una notificación emergente en el móvil"""
        url = f"https://api.telegram.org/bot{self.token}/answerCallbackQuery"
        payload = {"callback_query_id": callback_id, "text": text, "show_alert": True}
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout):
                pass
        except Exception:
            pass

    def register_pending_trade(self, signal_id: str, plan: Any, symbol_info: dict):
        """Registra un plan de trading a la espera de que el usuario pulse el botón en Telegram"""
        self.pending_trades[signal_id] = {
            "plan": plan,
            "symbol_info": symbol_info,
            "timestamp": time.time()
        }

    def start_callback_listener(self, on_confirm_callback: Callable):
        """Inicia el hilo en segundo plano que escucha los botones pulsados en Telegram"""
        if not self.enabled or self._listener_running:
            return
        self.on_trade_confirm_callback = on_confirm_callback
        self._listener_running = True
        self._listener_thread = threading.Thread(target=self._polling_loop, daemon=True)
        self._listener_thread.start()
        logger.info("🤖 [Telegram] Receptor interactivo de botones iniciado en segundo plano.")

    def stop_callback_listener(self):
        """Detiene el hilo receptor de Telegram"""
        self._listener_running = False

    def _polling_loop(self):
        offset = None
        while self._listener_running:
            try:
                url = f"https://api.telegram.org/bot{self.token}/getUpdates?timeout=4"
                if offset:
                    url += f"&offset={offset}"
                req = urllib.request.Request(url, headers={"User-Agent": "ModularTradingBot/1.0"})
                with urllib.request.urlopen(req, timeout=7) as res:
                    data = json.loads(res.read().decode())
                    for item in data.get("result", []):
                        offset = item["update_id"] + 1
                        cb = item.get("callback_query")
                        if not cb:
                            continue
                        self._handle_callback(cb)
            except Exception:
                time.sleep(1.5)

    def _handle_callback(self, cb: dict):
        cb_id = cb["id"]
        data = cb.get("data", "")

        if data.startswith("exec_"):
            sig_id = data.replace("exec_", "")
            trade_data = self.pending_trades.pop(sig_id, None)

            if not trade_data:
                self.answer_callback_query(cb_id, "⚠️ Esta señal ya expiró o fue ejecutada anteriormente.")
                return

            elapsed = time.time() - trade_data["timestamp"]
            if elapsed > self.signal_expiry_seconds:
                self.answer_callback_query(cb_id, f"⌛ La señal caducó ({int(elapsed/60)} min). El precio ha cambiado.")
                return

            # Ejecución confirmada por el usuario
            self.answer_callback_query(cb_id, "🚀 ¡Orden autorizada! Enviando al broker...")
            plan = trade_data["plan"]
            if self.on_trade_confirm_callback:
                self.on_trade_confirm_callback(plan, trade_data["symbol_info"])

            self.send_message(
                f"✅ <b>ORDEN AUTORIZADA DESDE EL MÓVIL</b>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"• <b>Activo:</b> <code>{plan.symbol}</code>\n"
                f"• <b>Operación:</b> <b>{plan.direction}</b>\n"
                f"• <b>Lote:</b> <code>{plan.lot_size}</code>\n"
                f"• <b>Estado:</b> <i>Enviada a ejecución</i>"
            )

        elif data.startswith("discard_"):
            sig_id = data.replace("discard_", "")
            self.pending_trades.pop(sig_id, None)
            self.answer_callback_query(cb_id, "❌ Operación descartada.")
            self.send_message("❌ <i>Operación descartada por el usuario.</i>")

    def notify_startup(self, active_strategy: str, symbols: list, timeframe: str, is_simulation: bool):
        mode = "🧪 SIMULACIÓN (DRY-RUN)" if is_simulation else "⚡ EN VIVO (BROKER REAL/DEMO)"
        msg = (
            f"🚀 <b>BOT DE TRADING INICIADO</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Modo:</b> <code>{mode}</code>\n"
            f"• <b>Estrategia:</b> <code>{active_strategy}</code>\n"
            f"• <b>Símbolos:</b> <code>{', '.join(symbols)}</code>\n"
            f"• <b>Temporalidad:</b> <code>{timeframe}</code>\n"
            f"• <b>Confirmación Móvil:</b> <code>{'ACTIVADA (Botón Requerido)' if self.execution_mode == 'confirmacion' else 'AUTOMÁTICA'}</code>\n"
            f"• <b>Estado:</b> <i>Vigilando mercado...</i>"
        )
        self.send_message(msg)

    def notify_signal(
        self,
        symbol: str,
        direction: str,
        price: float,
        reason: str,
        indicators: dict = None,
        sl: float = None,
        tp: float = None,
        signal_id: str = None,
        photo_bytes: bytes = None
    ) -> bool:
        if not self.notify_signals:
            return False

        icon = "🟢" if direction == "BUY" else "🔴"
        action = "COMPRA (BUY)" if direction == "BUY" else "VENTA (SELL)"

        levels_txt = ""
        if sl is not None and tp is not None:
            levels_txt = (
                f"\n• <b>Nivel Stop Loss:</b> <code>{sl:.5f}</code>"
                f"\n• <b>Nivel Take Profit:</b> <code>{tp:.5f}</code>"
            )

        ind_txt = ""
        if indicators:
            ind_txt = "\n• <b>Indicadores:</b> " + ", ".join([f"{k}: <code>{v}</code>" for k, v in indicators.items()])

        # Botones interactivos si estamos en modo confirmación
        inline_keyboard = None
        if self.execution_mode == "confirmacion" and signal_id:
            inline_keyboard = [[
                {"text": "🚀 ABRIR OPERACIÓN", "callback_data": f"exec_{signal_id}"},
                {"text": "❌ DESCARTAR", "callback_data": f"discard_{signal_id}"}
            ]]
            footer = "👇 <b>¿Autorizas abrir esta operación en el mercado?</b>\n<i>Presiona un botón para confirmar o descartar:</i>"
        else:
            footer = "⚡ <i>Orden abierta automáticamente por el bot</i>"

        msg = (
            f"{icon} <b>NUEVA SEÑAL PARA OPERAR</b> {icon}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Activo:</b> <code>{symbol}</code>\n"
            f"• <b>Operación:</b> <b>{action}</b>\n"
            f"• <b>Precio Entrada:</b> <code>{price:.5f}</code>"
            f"{levels_txt}\n"
            f"• <b>Motivo:</b> {reason}{ind_txt}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"{footer}"
        )

        if photo_bytes and self.send_screenshots:
            return self.send_photo(photo_bytes, msg, inline_keyboard)
        else:
            return self.send_message(msg, inline_keyboard)

    def notify_trade_opened(self, trade: dict) -> bool:
        if not self.notify_executions:
            return False
        icon = "📈" if trade["direction"] == "BUY" else "📉"
        mode = "[SIMULADO]" if trade.get("is_simulated", True) else "[REAL/DEMO]"
        msg = (
            f"{icon} <b>ORDEN EJECUTADA {mode}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Activo:</b> <code>{trade['symbol']}</code>\n"
            f"• <b>Operación:</b> <code>{trade['direction']}</code>\n"
            f"• <b>Lote:</b> <code>{trade['lot_size']}</code>\n"
            f"• <b>Precio Entrada:</b> <code>{trade['entry_price']}</code>\n"
            f"• <b>Stop Loss:</b> <code>{trade['stop_loss']}</code> (~{trade.get('sl_pips', 0)} pips)\n"
            f"• <b>Take Profit:</b> <code>{trade['take_profit']}</code> (~{trade.get('tp_pips', 0)} pips)\n"
            f"• <b>Riesgo Est:</b> <code>~${trade.get('risk_dollars', 0.0):,.2f}</code>"
        )
        return self.send_message(msg)

    def notify_trade_closed(self, trade: dict, close_price: float, hit_type: str) -> bool:
        if not self.notify_closes:
            return False
        if hit_type == "TP":
            icon = "🎯"
            title = "<b>TAKE PROFIT ALCANZADO (+GANANCIA)</b>"
        else:
            icon = "🛑"
            title = "<b>STOP LOSS ALCANZADO</b>"

        pips = trade.get("profit_pips", 0.0)
        pips_str = f"+{pips}" if pips > 0 else f"{pips}"

        msg = (
            f"{icon} {title}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Activo:</b> <code>{trade['symbol']}</code> ({trade['direction']})\n"
            f"• <b>Entrada:</b> <code>{trade['entry_price']}</code> ➔ <b>Salida:</b> <code>{close_price}</code>\n"
            f"• <b>Resultado:</b> <code>{pips_str} pips</code>\n"
            f"• <b>Estado:</b> <i>Cerrada</i>"
        )
        return self.send_message(msg)

    def notify_breakeven(self, symbol: str, new_sl: float) -> bool:
        msg = (
            f"🛡️ <b>BREAKEVEN ACTIVADO</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Activo:</b> <code>{symbol}</code>\n"
            f"• <b>Nuevo Stop Loss:</b> <code>{new_sl}</code> (Riesgo Cero)\n"
            f"• <b>Estado:</b> <i>Ganancias Aseguradas</i>"
        )
        return self.send_message(msg)
