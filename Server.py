import asyncio
import base64
import configparser
from log_conf import logger
from time import sleep
from urllib.parse import urlparse, ParseResult
from utils_db import db as ut
import cv2
import websockets
from onvif import ONVIFCamera
from pymodbus.client import ModbusTcpClient

REGISTERS = {
    'name': 0,
    'is_active': 1,
    'mode': 2,
    'cycles_current': 3,
    'cycles_total': 4,
    'oee': 5
}

config = configparser.ConfigParser()
config.read('D:/Diplom/config.ini')

if 'cntr' not in config:
    raise ValueError("Секция [cntr] не найдена в config.ini")
if 'cam' not in config:
    raise ValueError("Секция [cam] не найдена в config.ini")


def get_rtsp_url(ip, port, user, password):
    mycam = ONVIFCamera(ip, port, user, password)
    media_service = mycam.create_media_service()
    profiles = media_service.GetProfiles()
    stream_uri = media_service.GetStreamUri({
        'StreamSetup': {
            'Stream': 'RTP-Unicast',
            'Transport': {'Protocol': 'RTSP'}
        },
        'ProfileToken': profiles[8].token
    })

    return stream_uri.Uri


def add_auth_to_url(url, user, password):
    parsed = urlparse(url)
    netloc = f"{user}:{password}@{parsed.hostname}"
    if parsed.port:
        netloc += f":{parsed.port}"

    return ParseResult(
        scheme=parsed.scheme,
        netloc=netloc,
        path=parsed.path,
        params=parsed.params,
        query=parsed.query,
        fragment=parsed.fragment
    ).geturl()


async def stream_camera(websocket):
    rtsp_url = get_rtsp_url(config['cam']['host'], config['cam']['port'], config['cam']['username'],
                            config['cam']['password'])
    cap = cv2.VideoCapture(add_auth_to_url(rtsp_url, config['cam']['username'], config['cam']['password']))

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            img_base64 = base64.b64encode(buffer).decode('utf-8')

            await websocket.send(img_base64)
            await asyncio.sleep(0.03)  # ~30 FPS

    finally:
        cap.release()


def read_data(host, port):
    all_data = {}

    with ModbusTcpClient(host, port=port) as client:
        if not client.connect():
            logger.error("Не удалось подключиться к мастер-контроллеру")
            return None

        for slave_id in range(1, int(config['cntr']['slave_count']) + 1):
            try:
                response = client.read_holding_registers(
                    address=0,
                    count=len(REGISTERS),
                    slave=slave_id,
                )

                if response.isError():
                    logger.warning(f"Ошибка чтения данных slave {slave_id}")
                    continue

                registers = response.registers
                slave_data = {
                    'name': registers[REGISTERS['name']],
                    'is_active': registers[REGISTERS['is_active']],
                    'mode': registers[REGISTERS['mode']],
                    'cycles_current': registers[REGISTERS['cycles_current']],
                    'cycles_total': registers[REGISTERS['cycles_total']],
                    'oee': registers[REGISTERS['oee']]
                }

                all_data[f"slave_{slave_id}"] = slave_data
                logger.info(f"Данные slave {slave_id}: {slave_data}")

            except Exception as e:
                logger.error(f"Ошибка при чтении slave {slave_id}: {e}")

    return all_data


async def main():
    async with websockets.serve(stream_camera, "0.0.0.0", 8765):
        await asyncio.Future()


if __name__ == '__main__':
    asyncio.run(main())
    while True:
        try:
            logger.info("Запрос данных...")
            data = read_data(config['cntr']['host'], config['cntr']['port'])
            ut.update_robots(data)
            sleep(5)

        except KeyboardInterrupt:
            logger.info("Клиент остановлен")
            break
        except Exception as e:
            logger.error(f"Ошибка в основном цикле: {e}")
            sleep(10)
