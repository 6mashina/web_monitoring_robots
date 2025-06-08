import time
import traceback
from datetime import datetime
from functools import wraps

import pandas as pd
import plotly.express as px
import streamlit as st
from onvif import ONVIFCamera

from log_conf import logger
from models.camera import Camera
from models.robot import Robot
from models.room import Room
from utils_db import db as ut


def log_action(action: str):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger.info(f"Начато: {action}")
            try:
                result = func(*args, **kwargs)
                logger.info(f"Успешно: {action}")
                return result
            except Exception as e:
                logger.error(f"Ошибка при {action}: {str(e)}\n{traceback.format_exc()}")
                raise

        return wrapper

    return decorator


def cache_with_timeout(timeout: int):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = f"{func.__name__}_cache"
            if (cache_key not in st.session_state or
                    time.time() - st.session_state[f"{cache_key}_time"] > timeout):
                st.session_state[cache_key] = func(*args, **kwargs)
                st.session_state[f"{cache_key}_time"] = time.time()
                logger.debug(f"Обновлен кэш для {func.__name__}")

            return st.session_state[cache_key]

        return wrapper

    return decorator


@cache_with_timeout(5)
@log_action("получение данных о роботах")
def fetch_robots() -> list[Robot]:
    return ut.get_robots()


@cache_with_timeout(5)
@log_action("получение данных о камерах")
def fetch_cameras() -> list[Camera]:
    return ut.get_cameras()


@cache_with_timeout(5)
@log_action("получение данных о комнатах")
def fetch_rooms() -> list[Room]:
    return ut.get_rooms()


@log_action("проверка соединения с камерой")
def test_camera_connection(ip: str, port: int, timeout: int = 2) -> bool:
    try:
        mycam = ONVIFCamera(ip, port, 'admin', '888888')
        return True
    except Exception as e:
        logger.error(f"Ошибка подключения к камере {ip}:{port}: {str(e)}")
        return False


def format_number(num: int) -> str:
    return f"{num:,}".replace(",", " ").strip()


@log_action("инициализация сессии")
def init_session_state():
    if 'last_update' not in st.session_state:
        st.session_state.update({
            'last_update': None,
            'data_valid': False,
            'robots': [],
            'cameras': [],
            'filtered_robots': [],
            'log_messages': [],
            'editing_camera': None
        })
        update_session_data()


@log_action("обновление данных сессии")
def update_session_data():
    try:
        current_time = time.time()
        robots = fetch_robots()
        cameras = fetch_cameras()
        rooms = fetch_rooms()

        st.session_state.update({
            'last_update': current_time,
            'rooms': rooms,
            'data_valid': True,
            'robots': robots,
            'cameras': cameras,
            'filtered_robots': robots
        })

        logger.info(f"Данные обновлены. Роботов: {len(robots)}, Камер: {len(cameras)}")
        st.session_state.log_messages.append(
            f"{datetime.now().strftime('%H:%M:%S')} - Данные успешно обновлены"
        )

    except Exception as e:
        logger.error(f"Ошибка обновления данных: {str(e)}")
        st.session_state.data_valid = False
        st.session_state.log_messages.append(
            f"{datetime.now().strftime('%H:%M:%S')} - Ошибка обновления: {str(e)}"
        )


MODE_NAMES = {
    '0': "Работа",
    '1': "Стоп",
    '2': "Авария"
}

MODE_COLORS = {
    "0": "#28a745",  # зеленый
    "1": "#ffc107",  # желтый
    "2": "#dc3545"  # красный
}


def setup_page():
    st.set_page_config(
        page_title="Мониторинг роботов",
        page_icon="",
        layout="wide"
    )

    # Загрузка CSS и JS
    with open('styles.css', encoding='utf-8') as f:
        st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)

    with open("scr.js", "r", encoding="utf-8") as f:
        st.session_state.js_code = f.read()


def show_status_panel():
    if st.session_state.data_valid:
        last_update = datetime.fromtimestamp(st.session_state.last_update)
        st.sidebar.success(f"Данные актуальны на {last_update:%H:%M:%S}")
    else:
        st.sidebar.error("Данные требуют обновления")

    if st.sidebar.button("Обновить данные"):
        update_session_data()
        st.rerun()


def show_log_panel():
    with st.sidebar.expander("Журнал событий", expanded=False):
        if st.session_state.log_messages:
            st.text("\n".join(st.session_state.log_messages[-10:]))
        else:
            st.info("Журнал событий пуст")

        if st.button("Очистить журнал"):
            st.session_state.log_messages = []
            st.rerun()


def robot_card(robot: Robot) -> str:
    status_class = "status-active" if robot.is_active else "status-inactive"
    status_text = "Включен" if robot.is_active else "Выключен"

    return f"""
    <div class="robot-card">
        <h3>
            <span class="status-indicator" style="background-color: {MODE_COLORS.get(robot.mode, '#0066cc')}"></span>
            {robot.name} 
        </h3>
        <p>Статус: <span class="{status_class}">{status_text}</span></p>
        <p>Режим: {MODE_NAMES.get(robot.mode, robot.mode)}</p>
        <p>Циклов (текущая сессия): {format_number(robot.cycles_current)}</p>    
        <p>Комната: {ut.get_room(robot.room_id).name}</p>
        <p>Циклов (всего): {format_number(robot.cycles_total)}</p>
        <p>OEE: {robot.oee}%</p>
    </div>
    """


def show_robot_metrics(robots: list[Robot]):
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Всего роботов", len(robots))

    with col2:
        active = sum(1 for r in robots if r.is_active)
        st.metric("Активные роботы", active)

    with col3:
        avg_oee = round(sum(r.oee for r in robots) / len(robots), 1) if robots else 0
        st.metric("Средний OEE", f"{avg_oee}%")

    with col4:
        total_cycles = sum(r.cycles_total for r in robots)
        st.metric("Общее количество циклов", format_number(total_cycles))


def filter_robots(robots: list[Robot], filters: dict) -> list[Robot]:
    return [
        robot for robot in robots
        if (filters['status'] == "Все" or
            (filters['status'] == "Активные" and robot.is_active) or
            (filters['status'] == "Неактивные" and not robot.is_active))
           and MODE_NAMES.get(robot.mode, robot.mode) in filters['modes']
           and filters['search'].lower() in robot.name.lower()
           and ut.get_room(robot.room_id).name in filters['rooms']
    ]


def show_robot_management():
    st.subheader("Список роботов")

    with st.expander("Фильтры", expanded=False):
        status_filter = st.radio(
            "Статус работы",
            ["Все", "Активные", "Неактивные"],
            index=0
        )

        unique_modes = list(set(MODE_NAMES.get(r.mode, r.mode) for r in st.session_state.robots))
        selected_modes = st.multiselect(
            "Режим работы",
            options=unique_modes,
            default=unique_modes
        )
        unique_rooms = list(set(r.name for r in st.session_state.rooms))
        def_rooms = sorted(list(set(r['room_name'] for r in ut.get_rooms_wrobots())))
        selected_rooms = st.multiselect(
            "Расположение",
            options=unique_rooms,
            default=def_rooms
        )

        search_query = st.text_input("Поиск по названию", placeholder="Введите название робота")

    filters = {
        'status': status_filter,
        'modes': selected_modes,
        'rooms': selected_rooms,
        'search': search_query
    }
    st.session_state.filtered_robots = filter_robots(st.session_state.robots, filters)

    show_robot_metrics(st.session_state.filtered_robots)

    show_all = len(st.session_state.filtered_robots) <= 3 or st.checkbox("Показать всех роботов", value=False)
    display_robots = st.session_state.filtered_robots if show_all else st.session_state.filtered_robots[:3]

    for robot in display_robots:
        with st.container():
            st.markdown(robot_card(robot), unsafe_allow_html=True)

    if len(st.session_state.filtered_robots) > 3 and not show_all:
        st.info(f"Скрыто {len(st.session_state.filtered_robots) - 3} роботов")


def show_camera_management():
    st.subheader("Видеонаблюдение")
    robot_rooms = list(set(r.room_id for r in st.session_state.filtered_robots))
    rooms = [r for r in st.session_state.rooms if r.room_id in robot_rooms]
    cameras = [c for c in st.session_state.cameras if c.room_id in robot_rooms]

    if cameras and rooms:
        selected_camera = st.selectbox(
            "Выберите камеру:",
            options=[f"{c.name} ({ut.get_room(c.room_id).name})" for c in cameras]
        )

        html = f""" 
        <div class="video-container" style="
                    background-color: #1a1a1a;
                    border: 2px solid #0066cc;
                    height:300px;
                    border-radius: 8px; 
                    text-align: center;
                    margin: 0 auto;
                    display: flex; 
                    align-items: center; 
                    justify-content: center;  
                    overflow: hidden;  >
            <img id="video-feed" src="" style="width: 100%;
                                    height: auto; max-height: 100%;
                                    object-fit: contain;
                                    border-radius: 4px;">
        </div>
        <script>{st.session_state.js_code}</script>
        """
        st.components.v1.html(html, height=350)
    else:
        st.warning("Нет доступных камер для выбранных роботов")

    st.subheader("Управление камерами")
    with st.expander("*Добавить новую камеру*", expanded=False):
        add_camera_form()

    camera_list()


def add_camera_form():
    with st.form("add_camera_form"):
        col1, col2 = st.columns(2)
        with col1:
            camera_name = st.text_input("Название камеры*", placeholder="Камера 1")
            camera_ip = st.text_input("IP-адрес*", placeholder="192.168.1.100")
        with col2:
            camera_port = st.number_input("Порт*", min_value=1, max_value=65535, value=554)
            camera_location = st.selectbox("Местоположение*", [r.name for r in st.session_state.rooms])

        col1, col2 = st.columns(2)
        with col1:
            add_btn = st.form_submit_button("Добавить", use_container_width=True)
        with col2:
            test_btn = st.form_submit_button("Тест соединения", use_container_width=True)

        if add_btn and all([camera_name, camera_ip, camera_port, camera_location]):
            try:

                room_id = ut.get_room_by_name(camera_location).room_id
                new_camera = {
                    'name': camera_name,
                    'ip_address': camera_ip,
                    'port': camera_port,
                    'room_id': room_id
                }

                if ut.add_camera(new_camera):
                    st.success("Камера успешно добавлена!")
                    update_session_data()
                else:
                    st.error("Ошибка при добавлении камеры")
            except Exception as e:
                st.error(f"Ошибка: {str(e)}")
                logger.error(f"Ошибка добавления камеры: {traceback.format_exc()}")

        if test_btn and camera_ip:
            if test_camera_connection(camera_ip, camera_port):
                st.success("Соединение с камерой установлено")
            else:
                st.error("Не удалось подключиться к камере")


def camera_list():
    st.markdown(f"### Cписок камер")
    with st.expander("*Камеры*", expanded=False):
        st.markdown("**Активные камеры:**")
        for cmr in st.session_state.cameras:
            with st.container():
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.markdown(f"**{str.strip(cmr.name)}** ({ut.get_room(cmr.room_id).name})")
                    st.caption(f"IP: {cmr.ip_address}:{cmr.port}")

                with col2:
                    if st.button("⚙️", key=f"edit_{cmr.id}"):
                        st.session_state.editing_camera = cmr

                with col3:
                    if st.button("🗑️", key=f"delete_{cmr.id}"):
                        if ut.delete_camera(cmr.id):
                            st.success("Ок")
                            update_session_data()
                        else:
                            st.error("Ошибка при удалении")

    if st.session_state.editing_camera:
        edit_camera_form()


def edit_camera_form():
    ed_camera = st.session_state.editing_camera
    if not ed_camera:
        return

    with st.form(f"edit_camera_{ed_camera.id}"):
        st.markdown(f"**Редактирование {ed_camera.name}**")

        col1, col2 = st.columns(2)
        with col1:
            new_name = st.text_input("Название", value=ed_camera.name)
            new_ip = st.text_input("IP-адрес", value=ed_camera.ip_address)
        with col2:
            new_port = st.number_input("Порт", value=ed_camera.port, min_value=1, max_value=65535)
            locations = [room.name for room in ut.get_rooms()]
            new_location = st.selectbox(
                "Местоположение",
                options=locations,
                index=locations.index(ut.get_room(ed_camera.room_id).name)
            )

        col1, col2 = st.columns(2)
        with col1:
            if st.form_submit_button("Сохранить"):
                try:
                    new_room_id = ut.get_room_by_name(new_location).room_id
                    camera = Camera(None, new_name, new_ip, new_port, new_room_id)

                    if ut.update_camera(ed_camera.id, camera.__dict__):

                        st.success("Изменения сохранены!")
                        update_session_data()
                    else:
                        st.error("Ошибка при сохранении")
                except Exception as e:
                    st.error(f"Ошибка: {str(e)}")
                    logger.error(f"Ошибка обновления камеры: {traceback.format_exc()}")

        with col2:
            if st.form_submit_button("Отмена"):
                st.session_state.editing_camera = None
                st.rerun()


def show_mode_distribution():
    if not st.session_state.filtered_robots:
        return

    mode_data = pd.DataFrame({
        'mode': [r.mode for r in st.session_state.filtered_robots],
        'count': 1
    })

    if not mode_data.empty:
        mode_counts = mode_data.groupby('mode').count().reset_index()
        mode_counts['mode_name'] = mode_counts['mode'].map(MODE_NAMES)

        fig = px.pie(
            mode_counts,
            values='count',
            names='mode_name',
            title="Распределение режимов работы",
            color='mode',
            color_discrete_map=MODE_COLORS
        )

        st.plotly_chart(fig, use_container_width=True)


def main():
    setup_page()
    init_session_state()

    show_status_panel()
    show_log_panel()

    left_col, right_col = st.columns([2, 1])

    with left_col:
        show_robot_management()

    with right_col:
        show_camera_management()
        show_mode_distribution()


if __name__ == "__main__":
    main()
