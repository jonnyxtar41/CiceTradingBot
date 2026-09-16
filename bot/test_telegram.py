"""
Script de prueba para verificar la conexión con Telegram
Envía una captura de pantalla del gráfico de TradingView con botones interactivos a tu móvil.
"""
import time
from core.config_loader import load_config
from core.market_connector import SimulatedMarketConnector
from utils.chart_visualizer import generate_chart_snapshot
from utils.telegram_notifier import TelegramNotifier
from utils.logger import logger

def test_telegram():
    cfg = load_config()
    logger.info("Probando conexión con Telegram...")
    
    if not cfg.telegram.get("activo", False):
        logger.warning("Telegram está en 'activo: false' en config.yaml.")
        return

    notifier = TelegramNotifier(cfg.telegram)
    if not notifier.enabled:
        logger.error("No se pudo inicializar TelegramNotifier. Verifica token_bot y chat_id.")
        return

    # Iniciar receptor de botones para probar el toque en tu móvil
    def on_confirm(plan, symbol_info):
        logger.info(f"🎉 ¡ÉXITO! Recibida orden desde Telegram: {plan.direction} en {plan.symbol} a {plan.entry_price}")

    notifier.start_callback_listener(on_confirm)

    # Generar velas y captura gráfica
    connector = SimulatedMarketConnector()
    connector.connect()
    candles = connector.get_candles("EURUSD", "M15", 50)

    strat_params = cfg.get_strategy_params("rsi_bollinger")
    photo = generate_chart_snapshot(
        candles=candles,
        symbol="EURUSD",
        timeframe="M15",
        strategy_name="rsi_bollinger",
        strategy_params=strat_params,
        entry_price=1.08550,
        sl_price=1.08350,
        tp_price=1.08950,
        signal_direction="BUY"
    )

    class MockPlan:
        symbol = "EURUSD"
        direction = "BUY"
        entry_price = 1.08550
        stop_loss = 1.08350
        take_profit = 1.08950
        lot_size = 0.01

    signal_id = f"EURUSD_{int(time.time())}"
    notifier.register_pending_trade(signal_id, MockPlan(), {"point": 0.00001})

    logger.info("Enviando foto del gráfico con botones interactivos a Telegram...")
    success = notifier.notify_signal(
        symbol="EURUSD",
        direction="BUY",
        price=1.08550,
        reason="Prueba de Señal Interactiva con Gráfico TradingView",
        indicators={"RSI": "28.5", "BB_Inf": "1.08520"},
        sl=1.08350,
        tp=1.08950,
        signal_id=signal_id,
        photo_bytes=photo
    )

    if success:
        logger.info("✅ ¡Foto y botones enviados a tu móvil! Revisa tu Telegram y presiona [🚀 ABRIR OPERACIÓN].")
        logger.info("Esperando 15 segundos para recibir tu pulsación...")
        time.sleep(15)
    else:
        logger.error("❌ Falló el envío del mensaje. Revisa token y chat_id.")

    notifier.stop_callback_listener()
    connector.disconnect()

if __name__ == "__main__":
    test_telegram()

