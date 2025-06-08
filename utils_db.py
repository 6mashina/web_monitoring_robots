import configparser
from log_conf import logger
from pathlib import Path
from typing import Optional, List, Dict, Any, Union

import psycopg2
from psycopg2.extras import RealDictCursor

from models.camera import Camera
from models.robot import Robot
from models.room import Room

config = configparser.ConfigParser()
try:
    config.read(Path('D:/Diplom/config.ini').absolute())
    if 'db' not in config:
        raise ValueError("Секция [db] не найдена в config.ini")
except Exception as e:
    logger.critical(f"Ошибка загрузки конфигурации: {e}")
    raise


class Database:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_db()
        return cls._instance

    def _init_db(self):
        self.conn = None
        self._connect()

    def _connect(self):
        try:
            self.conn = psycopg2.connect(
                user=config['db']['username'],
                password=config['db']['password'],
                host=config['db']['host'],
                port=config['db']['port'],
                database=config['db']['database_name'],
                cursor_factory=RealDictCursor
            )
            logger.info("Успешное подключение к БД")
        except Exception as e:
            logger.critical(f"Ошибка подключения к БД: {e}")
            raise

    def execute_query(self, query: str, params: Union[tuple, dict, None] = None, fetch: bool = False):
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(query, params or ())
                if fetch:
                    return cursor.fetchall()
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Ошибка выполнения запроса: {query[:100]}... Параметры: {params}")
            logger.exception("Детали ошибки:")
            raise

    def get_cameras(self) -> List[Camera]:
        data = self.execute_query("SELECT * FROM cameras", fetch=True)
        return [Camera(**item) for item in data]

    def get_camera(self, camera_id: int) -> Optional[Camera]:
        data = self.execute_query(
            "SELECT * FROM cameras WHERE id = %s",
            (camera_id,),
            fetch=True
        )
        return Camera(**data[0]) if data else None

    def add_camera(self, camera: Dict[str, Any]) -> bool:
        query = """
            INSERT INTO cameras (name, ip_address, port, room_id)
            VALUES (%(name)s, %(ip_address)s, %(port)s, %(room_id)s)
            RETURNING *
        """
        result = self.execute_query(query, camera, fetch=False)
        return True

    def update_camera(self, camera_id: int, data: Dict[str, Any]) -> bool:
        data['id'] = camera_id
        query = """
            UPDATE cameras 
            SET name = %(name)s, ip_address = %(ip_address)s, 
                port = %(port)s, room_id = %(room_id)s
            WHERE id = %(id)s
            RETURNING *
        """
        result = self.execute_query(query, data, fetch=False)
        return True

    def delete_camera(self, camera_id: int) -> bool:
        self.execute_query("DELETE FROM cameras WHERE id = %s", (camera_id,))
        return True

    def get_rooms(self) -> List[Room]:
        data = self.execute_query("SELECT * FROM rooms", fetch=True)
        return [Room(**item) for item in data]

    def get_room(self, room_id: int) -> Optional[Room]:
        data = self.execute_query(
            "SELECT * FROM rooms WHERE room_id = %s",
            (room_id,),
            fetch=True
        )
        return Room(**data[0]) if data else None

    def get_room_by_name(self, name: str) -> Optional[Room]:
        data = self.execute_query(
            "SELECT * FROM rooms WHERE name = %s",
            (name,),
            fetch=True
        )
        return Room(**data[0]) if data else None

    def get_robots(self) -> List[Robot]:
        mode_colors = {"0": "#28a745", "1": "#ffc107", "2": "#dc3545"}
        data = self.execute_query("""
            SELECT id, name, is_active, mode, cycles_current, 
                   cycles_total, oee, room_id 
            FROM robots
        """, fetch=True)

        robots = []
        for item in data:
            robot = Robot(**item)
            robot.mode_color = mode_colors.get(robot.mode, "#6c757d")
            robots.append(robot)
        return robots

    def update_robots(self, robots_data: Dict[int, Dict[str, Any]]) -> None:
        query = """
            INSERT INTO robots (name, is_active, mode, cycles_current, cycles_total, oee)
            VALUES (%(name)s, %(is_active)s, %(mode)s, %(cycles_current)s, %(cycles_total)s, %(oee)s)
            ON CONFLICT (name) DO UPDATE SET
                is_active = EXCLUDED.is_active,
                mode = EXCLUDED.mode,
                cycles_current = EXCLUDED.cycles_current,
                cycles_total = EXCLUDED.cycles_total,
                oee = EXCLUDED.oee
        """
        with self.conn.cursor() as cursor:
            for data in robots_data.values():
                cursor.execute(query, {
                    'name': data['name'],
                    'is_active': bool(data['is_active']),
                    'mode': data['mode'],
                    'cycles_current': data['cycles_current'],
                    'cycles_total': data['cycles_total'],
                    'oee': data['oee']
                })
            self.conn.commit()

    def get_rooms_wrobots(self):
        query = """
                    SELECT 
                        r.name AS room_name,
                        r.room_id AS room_id
                    FROM robots rb
                    JOIN rooms r ON rb.room_id = r.room_id
                    ORDER BY r.room_id, rb.id
                """
        data = self.execute_query(query, fetch=True)
        return data

    def get_cameras_in_rooms(self, room_ids: List[int]) -> List[Dict[str, Any]]:
        query = """
            SELECT 
                r.name AS room_name,
                r.room_id,
                c.name AS camera_name,
                c.id AS camera_id
            FROM cameras c
            JOIN rooms r ON c.room_id = r.room_id
            WHERE r.room_id = ANY(%s)
            ORDER BY r.room_id, c.id
        """
        data = self.execute_query(query, (room_ids,), fetch=True)
        return data

    def __del__(self):
        if self.conn:
            self.conn.close()
            logger.info("Соединение с БД закрыто")


db = Database()
