from flask import Flask, request, jsonify
import os
import sys
import json
import re
import subprocess
from subprocess import Popen, PIPE
from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
from urllib.parse import urlparse, urlencode, parse_qs
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

UPLOAD_FOLDER = 'uploads'  # Папка для сохранения загруженных файлов
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
BINDINGS_FILE = 'bindings.json'

# Убедитесь, что папка для загрузок существует
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


class MyListener:
    def __init__(self):
        self.devices = {}  # Словарь для хранения информации о подключенных устройствах
        self.bindings = self.load_bindings()  # Загружаем привязки из файла

    def load_bindings(self):
        """Загружает привязки из файла или создает новый файл с пустыми данными."""
        if os.path.exists(BINDINGS_FILE):
            with open(BINDINGS_FILE, 'r') as f:
                return json.load(f)
        return {}  # Возвращаем пустой словарь, если файл не существует

    def save_bindings(self):
        """Сохраняет привязки в файл."""
        with open(BINDINGS_FILE, 'w') as f:
            json.dump(self.bindings, f)

    def bind_helmet_number(self, real_sn, helmet_number):
        """Привязывает номер шлема к real_sn."""
        if 0 <= helmet_number:
            self.bindings[real_sn] = {
                "helmet_number": helmet_number,
                "sensor_state": self.bindings.get(real_sn, {}).get("sensor_state", None)
                # Сохраняем текущее состояние сенсора
            }
            self.save_bindings()  # Сохраняем изменения
            return True
        return False

    def bind_helmet_sensor(self, real_sn, sensor_state):
        self.bindings[real_sn] = {
                "helmet_number": self.bindings.get(real_sn, {}).get("helmet_number", None),
                "sensor_state": sensor_state
                # Сохраняем текущее состояние сенсора
            }
        self.save_bindings()

    def get_helmet_number(self, real_sn):
        """Получает номер шлема по real_sn; если его нет - возвращает 0."""
        # Получаем привязку по real_sn
        binding = self.bindings.get(real_sn)

        if binding is not None:
            return binding.get("helmet_number", 0)  # Возвращаем номер шлема, если он есть, иначе 0
        return 0  # Возвращаем 0, если привязка не найдена

    def get_sensor_state(self, real_sn):
        binding = self.bindings.get(real_sn)

        if binding is not None:
            return binding.get("sensor_state", 0)  # Возвращаем номер шлема, если он есть, иначе 0
        return 0  # Возвращаем 0, если привязка не найдена

    def manage_proximity_sensor(self, device_serial_number, state):
        """Управляет сенсором приближения на устройстве Oculus и Pico."""

        # Получаем бренд устройства
        device_brand = self.get_device_brand(device_serial_number)

        if device_brand == "oculus":
            if state == 1:
                adb_command_disable = [
                    'adb', '-s', device_serial_number, 'shell',
                    'am', 'broadcast', '-a', 'com.oculus.vrpowermanager.automation_disable'
                ]
                shell_pipe_disable = Popen(adb_command_disable, stdout=PIPE)
                shell_output_disable = shell_pipe_disable.communicate()[0].decode("utf-8")
                shell_pipe_disable.wait()
                print(f"ADB Shell Output (Oculus Automation Disabled): {shell_output_disable}")
            elif state == 0:
                adb_command_enable = [
                    'adb', '-s', device_serial_number, 'shell',
                    'am', 'broadcast', '-a', 'com.oculus.vrpowermanager.prox_close'
                ]
                shell_pipe_enable = Popen(adb_command_enable, stdout=PIPE)
                shell_output_enable = shell_pipe_enable.communicate()[0].decode("utf-8")
                shell_pipe_enable.wait()
                print(f"ADB Shell Output (Oculus Proximity Sensor Enabled): {shell_output_enable}")

        elif device_brand == "pico":
            if state == 1:
                # Включаем сенсор приближения для Pico
                adb_command_enable_pico = [
                    'adb', '-s', device_serial_number, 'shell',
                    'setprop', 'persist.sys.proximity_sensor', '1'  # Включить сенсор
                ]
                shell_pipe_enable_pico = Popen(adb_command_enable_pico, stdout=PIPE)
                pico_output_enable = shell_pipe_enable_pico.communicate()[0].decode("utf-8")
                shell_pipe_enable_pico.wait()
                print(f"ADB Shell Output (Pico Proximity Sensor Enabled): {pico_output_enable}")

            elif state == 0:
                # Отключаем сенсор приближения для Pico
                adb_command_disable_pico = [
                    'adb', '-s', device_serial_number, 'shell',
                    'setprop', 'persist.sys.proximity_sensor', '0'  # Отключить сенсор
                ]
                shell_pipe_disable_pico = Popen(adb_command_disable_pico, stdout=PIPE)
                pico_output_disable = shell_pipe_disable_pico.communicate()[0].decode("utf-8")
                shell_pipe_disable_pico.wait()
                print(f"ADB Shell Output (Pico Proximity Sensor Disabled): {pico_output_disable}")

        # Сохраняем состояние сенсора в bindings
        real_sn = self.get_serial_number(device_serial_number)
        self.bind_helmet_sensor(real_sn, state)
        print(state)
        self.save_bindings()


    def is_device_connected(self, device_serial_number: str) -> bool:
        pipe = Popen(['adb', 'devices'], stdout=PIPE)
        output = pipe.communicate()[0].decode("utf-8")
        pipe.wait()
        return device_serial_number in output

    def do_stuff(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name)
        ip_bytes = info.addresses[0]
        ip_str = f"{ip_bytes[0]}.{ip_bytes[1]}.{ip_bytes[2]}.{ip_bytes[3]}"
        device_serial_number = f"{ip_str}:{info.port}"
        device_real_sn = self.get_serial_number(device_serial_number)

        if not self.is_device_connected(device_serial_number):
            print(f"Connecting to device {device_serial_number}...")

            # Проверяем, есть ли уже подключение по порту 5555
            if f"{ip_str}:5555" in self.devices:
                print(f"Device {device_serial_number} is already connected on port 5555.")
                return

            # Подключаемся к устройству по новому порту
            adb_connect_command = ['adb', 'connect', device_serial_number]
            pipe_connect = Popen(adb_connect_command, stdout=PIPE)
            connect_output = pipe_connect.communicate()[0].decode("utf-8")
            pipe_connect.wait()
            print(f"Connect Command Output: {connect_output}")

            # Подключаемся к устройству по новому порту
            adb_connect_command = ['adb', '-s' f"{ip_str}:5555" 'tcpip 5555']
            pipe_connect = Popen(adb_connect_command, stdout=PIPE)
            connect_output = pipe_connect.communicate()[0].decode("utf-8")
            pipe_connect.wait()
            print(f"TCPIP Output: {connect_output}")

            # Подключаемся к устройству по новому порту
            adb_connect_command = ['adb', 'connect', f"{ip_str}:5555"]
            pipe_connect = Popen(adb_connect_command, stdout=PIPE)
            connect_output = pipe_connect.communicate()[0].decode("utf-8")
            pipe_connect.wait()
            print(f"Connect Command Output: {connect_output}")

            # Получаем модель устройства
            device_model = self.get_device_model(device_serial_number)
            # Получаем бренд устройства
            device_brand = self.get_device_brand(device_serial_number)

            self.manage_proximity_sensor(device_serial_number, 0)

            # Добавляем устройство в список с моделью и брендом
            self.devices[device_serial_number] = {
                "ip": ip_str,
                "real_sn": device_real_sn,
                "model": device_model,
                "brand": device_brand  # Сохраняем бренд устройства
            }

    def get_device_model(self, device_serial_number):
        try:
            adb_command = [
                'adb', '-s', device_serial_number, 'shell', 'getprop', 'ro.product.model'
            ]
            pipe_model = Popen(adb_command, stdout=PIPE, stderr=PIPE)
            model_output, model_error = pipe_model.communicate()

            if pipe_model.returncode == 0:
                return model_output.decode('utf-8').strip()  # Возвращаем модель устройства
            else:
                print(f"Error getting device model: {model_error.decode('utf-8').strip()}")
                return None
        except Exception as e:
            print(f"Exception occurred while getting device model: {str(e)}")
            return None

    def get_device_brand(self, device_serial_number):
        """Получает бренд устройства по его серийному номеру."""
        try:
            adb_command = [
                'adb', '-s', device_serial_number, 'shell', 'getprop', 'ro.product.vendor.brand'
            ]
            pipe_brand = Popen(adb_command, stdout=PIPE, stderr=PIPE)
            brand_output, brand_error = pipe_brand.communicate()

            if pipe_brand.returncode == 0:
                return brand_output.decode('utf-8').strip()  # Возвращаем бренд устройства
            else:
                print(f"Error getting device brand: {brand_error.decode('utf-8').strip()}")
                return None
        except Exception as e:
            print(f"Exception occurred while getting device brand: {str(e)}")
            return None

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self.do_stuff(zc, type_, name)

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self.do_stuff(zc, type_, name)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        return

    def get_serial_number(self, device_serial_number: str) -> str:
        try:
            pipe = Popen(['adb', '-s', device_serial_number, 'shell', 'getprop', 'ro.serialno'], stdout=PIPE)
            serial_number = pipe.communicate()[0].decode("utf-8").strip()
            pipe.wait()
            return serial_number
        except Exception as e:
            print(f"Error getting serial number: {e}")
            return None


listener = MyListener()
zeroconf = Zeroconf()
ServiceBrowser(zeroconf, "_adb-tls-connect._tcp.local.", listener)
ServiceBrowser(zeroconf, "_adb_secure_connect._tcp.local.", listener)


@app.route('/connect', methods=['GET'])
def connect_device():
    if listener.devices:
        return jsonify({
            "status": "success",
            "devices": listener.devices  # Возвращаем список всех подключенных устройств
        }), 200
    else:
        return jsonify({"status": "error", "message": "No devices found."}), 404

@app.route('/bind_helmet', methods=['POST'])
def bind_helmet():
    data = request.get_json()
    real_sn = data.get('real_sn')
    helmet_number = data.get('helmet_number')

    if real_sn is None or helmet_number is None:
        return jsonify({"status": "error", "message": "real_sn and helmet_number are required."}), 400


    # Сохраняем привязку в словаре
    listener.bind_helmet_number(real_sn, helmet_number)

    return jsonify({"status": "success", "message": f"Bound {real_sn} to helmet number {helmet_number}."}), 200


@app.route('/toggle_sensor', methods=['POST'])
def toggle_sensor():
    """Переключает состояние сенсора для указанного real_sn."""
    data = request.get_json()
    real_sn = listener.get_serial_number(data.get('real_sn'))

    if real_sn is None:
        return jsonify({"status": "error", "message": "real_sn is required."}), 400

    # Получаем текущее состояние сенсора
    current_state = listener.get_sensor_state(real_sn)

    print(current_state)
    if current_state is None:
        return jsonify({"status": "error", "message": f"No sensor state found for real_sn {real_sn}."}), 404

    # Переключаем состояние
    new_state = 0 if current_state == 1 else 1

    # Управляем состоянием сенсора
    listener.manage_proximity_sensor(data.get('real_sn'), new_state)

    return jsonify({"status": "success", "message": f"Sensor state for {real_sn} toggled to {new_state}."}), 200
#@app.route('/check_devices', methods=['GET'])
def check_devices():
    # Здесь мы создаем тестовые данные вместо вызова adb
    connected_devices = {}

    for i in range(12):  # Генерируем 10 тестовых устройств
        serial_number = f"device_{i + 1}"
        real_sn = f"real_sn_{i + 1}"
        ip = f"192.168.1.{i + 1}"
        number = i + 1

        connected_devices[serial_number] = {
            "real_sn": real_sn,
            "ip": ip,
            "number": str(number),
            "model": "Quest 3",
        }

    return jsonify({"devices": connected_devices}), 200

@app.route('/check_devices', methods=['GET'])
def check_devices():
    pipe = Popen(['adb', 'devices'], stdout=PIPE)
    output = pipe.communicate()[0].decode("utf-8")
    pipe.wait()

    connected_devices = {}
    for line in output.splitlines()[1:]:  # Пропускаем первую строку заголовка
        if line.strip():  # Если строка не пустая
            parts = line.split()
            if len(parts) == 2:
                serial_number = parts[0]
                status = parts[1]

                if status == "offline":
                    continue

                # Проверяем, что устройство подключено по порту 5555
                if ':' in serial_number:
                    ip, port = serial_number.split(':')
                    if port != '5555':
                        continue  # Пропускаем устройства с портом, отличным от 5555

                real_sn = listener.get_serial_number(serial_number)
                num = listener.get_helmet_number(real_sn)
                if num is None:
                    num = 0
                connected_devices[serial_number] = {
                    "real_sn": real_sn,
                    "ip": serial_number if serial_number != real_sn else "-",
                    "number": str(num),
                    "model": listener.get_device_model(serial_number),
                    "sensor": str(listener.get_sensor_state(real_sn)),
                }
    return jsonify({"devices": connected_devices}), 200

def get_devices():
    pipe = Popen(['adb', 'devices'], stdout=PIPE)
    output = pipe.communicate()[0].decode("utf-8")
    pipe.wait()

    connected_devices = {}
    for line in output.splitlines()[1:]:  # Пропускаем первую строку заголовка
        if line.strip():  # Если строка не пустая
            parts = line.split()
            if len(parts) == 2:
                serial_number = parts[0]
                status = parts[1]

                if status == "offline":
                    continue

                # Проверяем, что устройство подключено по порту 5555
                if ':' in serial_number:
                    ip, port = serial_number.split(':')
                    if port != '5555':
                        continue  # Пропускаем устройства с портом, отличным от 5555

                real_sn = listener.get_serial_number(serial_number)
                num = listener.get_helmet_number(real_sn)
                connected_devices[serial_number] = {
                    "real_sn": real_sn,
                    "ip": serial_number if serial_number != real_sn else "-",
                    "number": str(num),
                }

    return connected_devices
@app.route('/launch_url', methods=['POST'])
def launch_url():
    data = request.get_json()
    device_serial_number = data.get('device_serial_number')
    url = update_url(data.get('url'))

    if not device_serial_number or not url:
        return jsonify({"status": "error", "message": "Device serial number and URL are required."}), 400

    adb_command_start = [
        'adb', '-s', device_serial_number,
        'shell', 'am', 'start',
        '-a', 'android.intent.action.VIEW',
        '-d', url,
        '-n com.antilatency.antilatencyservice/.MainActivity'
    ]

    shell_pipe_start = Popen(adb_command_start, stdout=PIPE)
    shell_output_start = shell_pipe_start.communicate()[0].decode("utf-8")
    shell_pipe_start.wait()

    print(f"ADB Shell Output (Start): {shell_output_start}")

    return jsonify({"status": "success", "output": shell_output_start}), 200

def update_url(url):
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    query_params['setAsDefault'] = ['true']
    query_params['silent'] = ['true']

    new_query_string = urlencode(query_params, doseq=True)
    new_query_string = new_query_string.replace('&', '%')
    new_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}?{new_query_string}?{new_query_string}"
    print(new_url)

    return new_url

@app.route('/upload_apk', methods=['POST'])
def upload_apk():
    # Получаем путь к файлу из формы
    file_path = request.form.get('file_path')

    if not file_path or not os.path.isfile(file_path):
        return jsonify({"status": "error", "message": "Invalid file path provided."}), 400

    if not file_path.endswith('.apk'):
        return jsonify({"status": "error", "message": "Only APK files are allowed."}), 400

    # Установка APK на устройство
    device_serial_number = request.form.get('device_serial_number')
    if not device_serial_number:
        return jsonify({"status": "error", "message": "Device serial number is required for installation."}), 400

    adb_command_install = [
        'adb', '-s', device_serial_number,
        'install', '--streaming', '-g', '-d', '-r', file_path
    ]

    print(f"Executing command: {' '.join(adb_command_install)}")

    # Запускаем команду ADB и захватываем вывод
    shell_pipe_install = Popen(adb_command_install, stdout=PIPE, stderr=PIPE)

    # Получаем код возврата и ошибки
    shell_output_install, shell_error_install = shell_pipe_install.communicate()

    print(f"Return code: {shell_pipe_install.returncode}")

    if shell_pipe_install.returncode == 0:
        return jsonify(
            {"status": "success", "message": f"File installed successfully from {file_path}"}), 200
    else:
        print(f"Installation failed: {shell_error_install.decode('utf-8')}")
        return jsonify(
            {"status": "error", "message": f"Installation failed: {shell_error_install.decode('utf-8') + " : " + shell_output_install.decode('utf-8')}"})


@app.route('/upload_apk_all', methods=['POST'])
def upload_apk_all():
    # Получаем файл из формы
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "No file part"}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({"status": "error", "message": "No selected file"}), 400

    if not file.filename.endswith('.apk'):
        return jsonify({"status": "error", "message": "Only APK files are allowed."}), 400

    # Сохраняем файл временно
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
    file.save(file_path)

    checked_devices = get_devices()
    print(checked_devices)
    responses = []

    def install_apk(device_serial_number):
        adb_command_install = [
            'adb', '-s', device_serial_number,
            'install', '--streaming', '-g', '-d', '-r', file_path
        ]

        print(f"Executing command: {' '.join(adb_command_install)}")

        shell_pipe_install = Popen(adb_command_install, stdout=PIPE, stderr=PIPE)
        shell_output_install, shell_error_install = shell_pipe_install.communicate()

        print(f"Return code: {shell_pipe_install.returncode}")

        if shell_pipe_install.returncode == 0:
            return {
                "serial_number": device_serial_number,
                "status": "success",
                "message": f"Installed on {device_serial_number}"
            }
        else:
            return {
                "serial_number": device_serial_number,
                "status": "error",
                "message": f"Installation failed on {device_serial_number}: {shell_error_install.decode('utf-8')} : {shell_output_install.decode('utf-8')}"
            }

    # Используем ThreadPoolExecutor для параллельной установки
    with ThreadPoolExecutor() as executor:
        future_to_device = {executor.submit(install_apk, device): device for device in checked_devices}

        for future in as_completed(future_to_device):
            response = future.result()
            responses.append(response)

    return jsonify(responses), 200


@app.route('/get_battery_status', methods=['POST'])
def get_battery_status():
    device_serial_number = request.json.get('device_serial_number')

    if not device_serial_number:
        return jsonify({"status": "error", "message": "Device serial number is required."}), 400

    adb_command_battery = [
        'adb', '-s', device_serial_number,
        'shell', 'dumpsys', 'battery'
    ]

    shell_pipe_battery = Popen(adb_command_battery, stdout=PIPE, stderr=PIPE)
    shell_output_battery, shell_error_battery = shell_pipe_battery.communicate()
    shell_pipe_battery.wait()

    if shell_pipe_battery.returncode == 0:
        output = shell_output_battery.decode('utf-8')
        # Извлечение уровня заряда из вывода
        for line in output.splitlines():
            if "level" in line:
                battery_level = line.split(":")[1].strip()
                return jsonify({"status": "success", "battery_level": battery_level}), 200
    else:
        return jsonify(
            {"status": "error", "message": f"Failed to get battery status: {shell_error_battery.decode('utf-8')}"})

    return jsonify({"status": "error", "message": "Could not retrieve battery status."}), 500


@app.route('/get_oculus_controller_battery_status', methods=['POST'])
def get_oculus_controller_battery_status():
    device_serial_number = request.json.get('device_serial_number')

    if not device_serial_number:
        return jsonify({"status": "error", "message": "Device serial number is required."}), 400

    # Команда для получения информации о батарее контроллеров
    adb_command = [
        'adb', '-s', device_serial_number, 'shell', 'dumpsys', 'OVRRemoteService | grep Paired'
    ]
    shell_pipe = Popen(adb_command, stdout=PIPE, stderr=PIPE)
    shell_output, shell_error = shell_pipe.communicate()
    shell_pipe.wait()

    if shell_pipe.returncode == 0:
        output = shell_output.decode('utf-8')
        battery_status = {}

        # Разделение строки на отдельные устройства
        devices = output.strip().split('\n')

        # Словарь для хранения информации о контроллерах
        controller_info = {}

        # Обработка каждой строки
        for device in devices:
            # Извлечение типа контроллера
            type_match = re.search(r'Type:\s*(\w+)', device)
            # Извлечение уровня заряда батареи
            battery_match = re.search(r'Battery:\s*(\d+)%', device)

            if type_match and battery_match:
                controller_type = type_match.group(1)
                battery_level = battery_match.group(1)  # Извлекаем уровень заряда без '%'
                controller_info[controller_type] = battery_level
                if controller_type == "Right":
                    battery_status['r'] = battery_level
                else:
                    battery_status['l'] = battery_level

        return jsonify({"status": "success", "battery_status": battery_status}), 200
    else:
        return jsonify({"status": "error", "message": f"Failed to get battery status: {shell_error.decode('utf-8')}"})


@app.route('/get_installed_apps', methods=['POST'])
def get_installed_apps():
    data = request.get_json()
    device_serial_number = data.get('device_serial_number')

    if not device_serial_number:
        return jsonify({"status": "error", "message": "Device serial number is required."}), 400

    adb_command = [
        'adb', '-s', device_serial_number, 'shell', 'pm', 'list', 'packages'
    ]

    shell_pipe = Popen(adb_command, stdout=PIPE)
    shell_output, shell_error = shell_pipe.communicate()

    if shell_pipe.returncode == 0:
        packages = shell_output.decode('utf-8').splitlines()

        # Список запрещенных пакетов
        banned_packages = [
            'com.oculus',
            'com.android',
            'com.meta',
            'com.facebook',
            'com.whatsapp',
            'com.qualcomm',
            'horizonos.platform',
            'oculus.platform',
            'android',
            'com.pvr',
            'com.pico',
            'com.sohu',
            'com.pxr',
            'com.qti',
            'com.ss',
            'com.bytedance',
            'com.google',
            'nextapp.fx',
            'vendor'
        ]

        # Фильтруем пакеты, исключая запрещенные и те, что без package:
        apps = [
            pkg.replace('package:', '').strip() for pkg in packages
            if pkg.startswith('package:') and not any(pkg.startswith(f'package:{banned}') for banned in banned_packages)
        ]

        return jsonify({"status": "success", "apps": apps}), 200
    else:
        return jsonify({"status": "error",
                        "message": f"Failed to get installed apps for device {device_serial_number}"}), 500


@app.route('/launch_app', methods=['POST'])
def launch_app():
    data = request.get_json()
    device_serial_number = data.get('device_serial_number')
    package_name = data.get('package_name')

    if not device_serial_number or not package_name:
        return jsonify({"status": "error", "message": "Device serial number and package name are required."}), 400

    # Преобразуем строку package:com.oneplus.calculator в com.oneplus.calculator
    package_name = package_name.replace('package:', '')

    adb_command_start = [
        'adb', '-s', device_serial_number,
        'shell', 'monkey', '-p', package_name, '1'
    ]

    print(adb_command_start)
    try:
        shell_pipe_start = Popen(adb_command_start, stdout=PIPE, stderr=PIPE)
        shell_output_start, shell_error_start = shell_pipe_start.communicate()

        if shell_pipe_start.returncode == 0:
            output_decoded = shell_output_start.decode('utf-8').strip()
            return jsonify({"status": "success", "output": output_decoded}), 200
        else:
            error_decoded = shell_error_start.decode('utf-8').strip()
            return jsonify({"status": "error", "message": f"Failed to launch app: {error_decoded}"}), 500

    except Exception as e:
        return jsonify({"status": "error", "message": f"An exception occurred: {str(e)}"}), 500

@app.route('/launch_home', methods=['POST'])
def launch_home():
    data = request.get_json()
    device_serial_number = data.get('device_serial_number')

    if not device_serial_number:
        return jsonify({"status": "error", "message": "Device serial number is required."}), 400

    # Формируем команду ADB для запуска главного экрана
    adb_command_start = [
        'adb', '-s', device_serial_number,
        'shell', 'am', 'start', '-a', 'android.intent.action.MAIN',
        '-c', 'android.intent.category.HOME'
    ]

    print(adb_command_start)
    try:
        shell_pipe_start = Popen(adb_command_start, stdout=PIPE, stderr=PIPE)
        shell_output_start, shell_error_start = shell_pipe_start.communicate()

        if shell_pipe_start.returncode == 0:
            output_decoded = shell_output_start.decode('utf-8').strip()
            return jsonify({"status": "success", "output": output_decoded}), 200
        else:
            error_decoded = shell_error_start.decode('utf-8').strip()
            return jsonify({"status": "error", "message": f"Failed to launch home: {error_decoded}"}), 500

    except Exception as e:
        return jsonify({"status": "error", "message": f"An exception occurred: {str(e)}"}), 500

@app.route('/start_stream', methods=['POST'])
def start_scrcpy():
    # Получаем серийный номер из запроса
    data = request.json
    serial_number = data.get('serial_number')

    if not serial_number:
        return jsonify({"status": "error", "message": "Serial number is required."}), 400

    # Путь к файлу .bat (предполагается, что он находится в той же папке, что и этот скрипт)
    bat_file_path = resource_path('open_a_terminal_here.bat')
    print(bat_file_path)
    # Проверяем, существует ли файл .bat
    if not os.path.isfile(bat_file_path):
        return jsonify({"status": "error", "message": f"Batch file not found: {bat_file_path}"}), 404

    try:
        # Запускаем файл .bat
        subprocess.Popen([bat_file_path], shell=True)

        print(listener.get_device_model(serial_number))
        model = listener.get_device_model(serial_number)
        window_title = f'{listener.get_device_brand(serial_number)} {model} helmet № {listener.get_helmet_number(listener.get_serial_number(serial_number))}'
        # Формируем команду scrcpy с серийным номером
        command = f'scrcpy -s {serial_number} --video-bit-rate 16M {get_crop_command(model)} --video-buffer=20 --max-fps 30 --window-title="{window_title}"'

        # Запускаем команду scrcpy
        subprocess.Popen(command, shell=True)

        return jsonify({"status": "success", "message": f"Started scrcpy for device {serial_number}."}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def get_crop_command(model):
    match model:
        case 'Quest 3':
            return '--crop 1778:1039:2200:549'
        case 'Quest 2':
            return '--crop 1600:900:1920:1080'
        case 'A9210':
            return '--crop 1792:1008:2400:549'
        case _:
            return ''

def resource_path(relative_path):
    """ Получает абсолютный путь к ресурсу, работает как для разработки, так и для PyInstaller """
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)

if __name__ == '__main__':
    try:
        app.run(host='127.0.0.1', port=5000)
    except KeyboardInterrupt:
        pass
    finally:
        zeroconf.close()