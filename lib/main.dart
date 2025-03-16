import 'dart:async';
import 'dart:io';
import 'dart:ui';
import 'package:auto_size_text/auto_size_text.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';
import 'package:file_picker/file_picker.dart';
import 'package:get_ip_address/get_ip_address.dart';
import 'package:path/path.dart' as path;
import 'package:flutter/widgets.dart';
import 'package:flutter/foundation.dart';

void main() {
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return const MaterialApp(
      title: 'Flutter ADB Connect',
      home: MyHomePage(),
    );
  }
}

class MyHomePage extends StatefulWidget {
  const MyHomePage({super.key});

  @override
  _MyHomePageState createState() => _MyHomePageState();
}

class _MyHomePageState extends State<MyHomePage> {
  final List<Map<String, String>> _devicesList = []; // Список подключенных устройств
  Process? _serverProcess; // Ссылка на процесс сервера
  Timer? _batteryStatusTimer; // Таймер для обновления статуса батареи
  Timer? _deviceCheckTimer; // Таймер для проверки состояния устройств
  String localIp = "0.0.0.0";
  Map<String, List<String>> _installedApps = {};
  String? _selectedApp;
  late final AppLifecycleListener _listener;

  @override
  void initState() {
    super.initState();
    _listener = AppLifecycleListener(
      onExitRequested: _onExitRequested,
    );
    getLocalIP().then((ip) {
      localIp = "http://$ip:5000";
      print(localIp);
      startServer(); // Запуск сервера при старте приложения
      _fetchDevices(); // Запрос списка устройств после запуска сервера

      // Запускаем таймер для проверки состояния устройств каждые 1 секунду
      _deviceCheckTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
        _fetchDevices();
      });
    });
  }


  Future<String> getLocalIP() async {
    return '127.0.0.1';
    /// Инициализация IP-адреса
    var ipAddress = IpAddress(type: RequestType.json);

    /// Получаем IP-адрес на основе типа запроса.
    dynamic data = await ipAddress.getIp();

    // Проверяем, получен ли IP-адрес, и возвращаем его или выбрасываем исключение
    if (data != null && data['ip'] != null) {
      return data['ip']; // Возвращаем только значение IP-адреса
    } else {
      throw Exception("Не удалось получить локальный IP-адрес");
    }
  }

  Future<AppExitResponse> _onExitRequested() async {
    await killAllServerProcesses();
    return AppExitResponse.exit;
  }

  @override
  void dispose() {
    stopServer(); // Остановка сервера при закрытии приложения
    if (_batteryStatusTimer != null) {
      _batteryStatusTimer!.cancel();
    }
    super.dispose();
  }

  void startServer() async {
    if(kDebugMode){
      return;
    }
    // Определите относительный путь к исполняемому файлу server.exe
    if(!Platform.isWindows){
      return;
    }
    final executablePath = path.join(
      Directory(Platform.resolvedExecutable).parent.path,
      'server', // Папка, где находится server.exe
      'server.exe', // Имя вашего исполняемого файла
    );

    // Проверьте, существует ли исполняемый файл
    if (await File(executablePath).exists()) {
      try {
        // Запустите процесс сервера
        _serverProcess = await Process.start(
          executablePath,
          [],
          mode: ProcessStartMode.inheritStdio,
        );

        print('Сервер запущен');
      } catch (e) {
        print('Ошибка при запуске сервера: $e');
      }
    } else {
      print('Исполняемый файл server.exe не найден.');
    }
  }

  void stopServer() async {
    if (_serverProcess != null) {
      _serverProcess!.kill(ProcessSignal.sigterm); // Остановка процесса
      _serverProcess = null; // Сброс ссылки на процесс
      print('Server stopped');
    }
  }

  Future<void> killAllServerProcesses() async {
    // Execute the tasklist command to get all running processes
    ProcessResult result = await Process.run('tasklist', []);

    // Check if the command was successful
    if (result.exitCode == 0) {
      // Split the output into lines
      List<String> lines = result.stdout.split('\n');

      // Iterate through each line to find processes named server.exe
      for (String line in lines) {
        if (line.contains('server.exe')) {
          // Extract the PID from the line
          var parts = line.split(RegExp(r'\s+')); // Split by whitespace
          if (parts.length > 1) {
            String pid = parts[1]; // PID is usually the second element

            print('Завершение процесса с PID: $pid');
            await Process.run('taskkill', ['/F', '/PID', pid]); // Kill the process
          }
        }
      }
    } else {
      print('Ошибка при получении списка процессов: ${result.stderr}');
    }
  }

  Future<void> _fetchDevices() async {
    final response = await http.get(Uri.parse('$localIp/check_devices'));

    if (response.statusCode == 200) {
      final data = json.decode(response.body);

      setState(() {
        _devicesList.removeWhere((device) => !data['devices'].containsKey(device['serial_number']));
        data['devices'].forEach((key, value) {
          bool deviceExists = _devicesList.any((device) => device['serial_number'] == key);
          if(!deviceExists) {
            _devicesList.add({
              'serial_number': key,
              'ip': value['ip'],
              'real_sn': value['real_sn'],
              'number': value['number'],
              'model': value['model'],
              'sensor': value['sensor'],
              'battery_level': '0', // Изначально уровень заряда неизвестен
              'battery_r': '0',  // Изначально уровень заряда неизвестен
              'battery_l': '0',  // Изначально уровень заряда неизвестен
            });
          }
          else{
            int index = _devicesList.indexWhere((device) => device['serial_number'] == key);
            _devicesList[index]['number'] = value['number'];
            _devicesList[index]['sensor'] = value['sensor'];
          }
        });
      });
      for (var device in _devicesList) {
        _getBatteryStatus(device['serial_number']!);
        _fetchInstalledApps(device['serial_number']!);
      }
    } else {
      setState(() {
        _devicesList.clear();
      });
      print("Error fetching devices");
    }
  }

  Future<void> _getBatteryStatus(String serialNumber) async {
    final response = await http.post(
      Uri.parse('$localIp/get_battery_status'),
      headers: {'Content-Type': 'application/json'},
      body: json.encode({
        'device_serial_number': serialNumber,
      }),
    );

    String batteryLevel = "0"; // Изначально устанавливаем значение "-"
    String batteryR = "0"; // Уровень заряда правого контроллера
    String batteryL = "0"; // Уровень заряда левого контроллера

    if (response.statusCode == 200) {
      final data = json.decode(response.body);
      batteryLevel = data['battery_level'];
    }

    // Получаем заряд контроллеров
    final controllerResponse = await http.post(
      Uri.parse('$localIp/get_oculus_controller_battery_status'),
      headers: {'Content-Type': 'application/json'},
      body: json.encode({
        'device_serial_number': serialNumber,
      }),
    );

    if (controllerResponse.statusCode == 200) {
      final controllerData = json.decode(controllerResponse.body);
      if (controllerData['status'] == "success") {
        batteryR = controllerData['battery_status']['r'] ?? "0";
        batteryL = controllerData['battery_status']['l'] ?? "0";
      }
    }

    setState(() {
      // Обновляем уровень заряда в списке устройств
      for (var device in _devicesList) {
        if (device['serial_number'] == serialNumber) {
          device['battery_level'] = batteryLevel; // Обновляем уровень заряда устройства
          device['battery_r'] = batteryR; // Обновляем уровень заряда правого контроллера
          device['battery_l'] = batteryL; // Обновляем уровень заряда левого контроллера
        }
      }
    });
  }

  Future<void> _uploadApk(String serialNumber) async {
    FilePickerResult? result = await FilePicker.platform.pickFiles(type: FileType.custom, allowedExtensions: ['apk']);

    if (result != null && result.files.isNotEmpty) {
      var filePath = result.files.single.path;

      // Показать сообщение о начале загрузки
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Uploading APK to $serialNumber...')),
      );

      showDialog(
        context: context,
        barrierDismissible: false,
        builder: (BuildContext context) {
          return const AlertDialog(
            title: Text('Uploading'),
            content: Row(
              children: [
                CircularProgressIndicator(),
                SizedBox(width: 20),
                Text('Please wait...'),
              ],
            ),
          );
        },
      );

      var request = http.MultipartRequest('POST', Uri.parse('$localIp/upload_apk'));

      // Добавление серийного номера устройства и пути к файлу в запрос
      request.fields['device_serial_number'] = serialNumber;
      request.fields['file_path'] = filePath!; // Отправляем путь к файлу

      var response = await request.send();

      Navigator.of(context).pop();

      if (response.statusCode == 200) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('APK uploaded successfully to $serialNumber!')),
        );
        print("APK uploaded successfully to $serialNumber");
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error uploading APK to $serialNumber')),
        );
        print("Error uploading APK to $serialNumber");
      }
    }
  }

  Future<void> _uploadApkAll() async {
    FilePickerResult? result =
    await FilePicker.platform.pickFiles(type: FileType.custom, allowedExtensions: ['apk']);

    if (result != null && result.files.isNotEmpty) {
      var filePath = result.files.single.path;

      // Показать сообщение о начале загрузки для всех устройств
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Uploading APK to all devices...')),
      );

      showDialog(
        context: context,
        barrierDismissible: false,
        builder: (BuildContext context) {
          return const AlertDialog(
            title: Text('Uploading'),
            content: Row(
              children: [
                CircularProgressIndicator(),
                SizedBox(width: 20),
                Text('Please wait...'),
              ],
            ),
          );
        },
      );

      var request = http.MultipartRequest('POST', Uri.parse('$localIp/upload_apk_all'));

      // Измените здесь имя поля на 'file'
      request.files.add(await http.MultipartFile.fromPath('file', filePath!));

      var response = await request.send();

      Navigator.of(context).pop();

      if (response.statusCode == 200) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('APK uploaded to all devices successfully!')),
        );
        print("APK uploaded to all devices successfully");
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Error uploading APK to all devices')),
        );
        print("Error uploading APK to all devices");
      }
    }
  }

  Future<void> _launchUrl(String serialNumber) async {
    String? url; // Переменная для хранения введенного URL

    // Показать диалоговое окно для ввода URL
    await showDialog<String>(
      context: context,
      builder: (BuildContext context) {
        TextEditingController urlController = TextEditingController(); // Контроллер для текстового поля
        return AlertDialog(
          title: const Text('Antilatency link'),
          content: TextField(
            controller: urlController,
            decoration: const InputDecoration(hintText: 'Введите карту antilatency'),
          ),
          actions: <Widget>[
            TextButton(
              onPressed: () => Navigator.pop(context), // Закрыть без действия
              child: const Text('Отменить'),
            ),
            TextButton(
              onPressed: () {
                url = urlController.text; // Получаем введенный URL
                Navigator.pop(context); // Закрываем диалог
              },
              child: const Text('Добавить'),
            ),
          ],
        );
      },
    );

    // Если URL был введен, отправляем запрос на сервер
    if (url != null) {
      final response = await http.post(
        Uri.parse('$localIp/launch_url'),
        headers: {'Content-Type': 'application/json'},
        body: json.encode({
          'device_serial_number': serialNumber,
          'url': url,
        }),
      );

      if (response.statusCode == 200) {
        print("URL launched successfully");
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('URL launched successfully!')));
      } else {
        print("Error launching URL on device $serialNumber: ${response.body}");
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Error launching URL')));
      }
    }
  }

  Future<void> _launchUrlAll() async {
    String? url; // Переменная для хранения введенного URL

    // Показать диалоговое окно для ввода URL
    await showDialog<String>(
      context: context,
      builder: (BuildContext context) {
        TextEditingController urlController = TextEditingController(); // Контроллер для текстового поля
        return AlertDialog(
          title: const Text('Antilatency link'),
          content: TextField(
            controller: urlController,
            decoration: const InputDecoration(hintText: 'Введите карту antilatency'),
          ),
          actions: <Widget>[
            TextButton(
              onPressed: () => Navigator.pop(context), // Закрыть без действия
              child: const Text('Отменить'),
            ),
            TextButton(
              onPressed: () {
                url = urlController.text; // Получаем введенный URL
                Navigator.pop(context); // Закрываем диалог
              },
              child: const Text('Добавить'),
            ),
          ],
        );
      },
    );

    // Если URL был введен, отправляем запрос на сервер для всех устройств
    if (url != null) {
      for (var device in _devicesList) {
        final response = await http.post(
          Uri.parse('$localIp/launch_url'),
          headers: {'Content-Type': 'application/json'},
          body: json.encode({
            'device_serial_number': device['serial_number'],
            'url': url,
          }),
        );

        if (response.statusCode == 200) {
          print("URL launched successfully on ${device['serial_number']}");
        } else {
          print("Error launching URL on ${device['serial_number']}: ${response.body}");
        }
      }

      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('URL launched on all devices!')));
    }
  }

  Future<void> _bindHelmetNumber(String realSn, int shlemNumber) async {
    final response = await http.post(
      Uri.parse('$localIp/bind_helmet'),
      headers: {'Content-Type': 'application/json'},
      body: json.encode({'real_sn': realSn, 'helmet_number': shlemNumber}),
    );

    if (response.statusCode == 200) {
      final data = json.decode(response.body);
      print(data['message']); // Успешное сообщение
      // Обновите состояние, если необходимо
    } else {
      print("Error binding shlem number: ${response.body}");
    }
  }

  Future<void> _toggleSensorState(String realSn) async {
    final response = await http.post(
      Uri.parse('$localIp/toggle_sensor'),
      headers: {'Content-Type': 'application/json'},
      body: json.encode({'real_sn': realSn}),
    );

    if (response.statusCode == 200) {
      final data = json.decode(response.body);
      print(data['message']); // Успешное сообщение о переключении состояния сенсора
      // Обновите состояние, если необходимо
    } else {
      print("Error toggling sensor state: ${response.body}");
    }
  }

  Future<void> _fetchInstalledApps(String serialNumber) async {
    final response = await http.post(
      Uri.parse('$localIp/get_installed_apps'), // URL вашего сервера
      headers: {'Content-Type': 'application/json'},
      body: json.encode({'device_serial_number': serialNumber}),
    );

    if (response.statusCode == 200) {
      setState(() {
        // Извлекаем имена пакетов из результата
        final data = json.decode(response.body);
        _installedApps[serialNumber] = List<String>.from(data['apps']);
      });
    } else {
      // Обработка ошибок
      print("Error fetching installed apps: ${response.body}");
    }
  }

  Future<void> _launchApp(String serialNumber, String packageName) async {
    final response = await http.post(
      Uri.parse('$localIp/launch_app'), // URL вашего сервера
      headers: {'Content-Type': 'application/json'},
      body: json.encode({
        'device_serial_number': serialNumber,
        'package_name': packageName,
      }),
    );

    if (response.statusCode == 200) {
      print("App launched successfully");
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('App launched successfully!')));
    } else {
      print("Error launching app on device $serialNumber: ${response.body}");
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Error launching app')));
    }
  }

  // Метод для отображения диалога выбора приложения
  void _showLaunchAppDialog(String serialNumber) {
    // Получаем установленные приложения для данного серийного номера
    List<String>? appsForDevice = _installedApps[serialNumber];

    showDialog(
      context: context,
      builder: (BuildContext context) {
        return AlertDialog(
          title: const Text('Выберите приложение для запуска'),
          content: StatefulBuilder(
            builder: (BuildContext context, StateSetter setState) {
              return DropdownButton<String>(
                hint: Text('Выберите приложение'),
                value: _selectedApp,
                onChanged: (String? newValue) {
                  setState(() {
                    _selectedApp = newValue; // Обновляем состояние выбранного приложения
                  });
                },
                items: appsForDevice?.map<DropdownMenuItem<String>>((String value) {
                  return DropdownMenuItem<String>(
                    value: value,
                    child: Text(value),
                  );
                }).toList() ?? [], // Если нет приложений, возвращаем пустой список
              );
            },
          ),
          actions: <Widget>[
            TextButton(
              onPressed: () => Navigator.of(context).pop(), // Закрыть без действия
              child: const Text('Отмена'),
            ),
            TextButton(
              onPressed: () {
                if (_selectedApp != null) {
                  _launchApp(serialNumber, _selectedApp!);
                  Navigator.of(context).pop(); // Закрыть диалог
                }
              },
              child: const Text('Запустить'),
            ),
          ],
        );
      },
    );
  }

  // Метод для запуска приложения на всех устройствах из списка
  Future<void> _launchAppOnAllDevices(String packageName) async {
    print("launch all");
    for (var device in _devicesList) {
      String serialNumber = device['serial_number']!;
      // Проверяем, есть ли приложение в списке для данного устройства
      if (_installedApps[serialNumber]?.contains(packageName) ?? false) {
        await _launchApp(serialNumber, packageName);
      } else {
        print("Приложение $packageName не найдено на устройстве $serialNumber");
      }
    }
  }

  Future<void> _startDeviceStreaming(String serialNumber) async {
    // Формируем POST-запрос
    final response = await http.post(
      Uri.parse('$localIp/start_stream'), // URL вашего сервера
      headers: {'Content-Type': 'application/json'},
      body: json.encode({
        'serial_number': serialNumber,
      }),
    );

    // Обработка ответа от сервера
    if (response.statusCode == 200) {
      print("Stream started successfully for device: $serialNumber");
    } else {
      print("Error starting stream for device $serialNumber: ${response.body}");
    }
  }

  Future<void> _launchHome(String serialNumber) async {
    // URL вашего сервера
    final String url = '$localIp/launch_home';

    // Формируем POST-запрос
    final response = await http.post(
      Uri.parse(url),
      headers: {'Content-Type': 'application/json'},
      body: json.encode({
        'device_serial_number': serialNumber,
      }),
    );

    // Обработка ответа от сервера
    if (response.statusCode == 200) {
      print("Home launched successfully for device: $serialNumber");
    } else {
      print("Error launching home for device $serialNumber: ${response.body}");
    }
  }

  String _getImageHelmetPath(String model) {
    switch (model) {
      case 'Quest 3':
        return 'assets/images/quest_3.jpg';
      case 'A9210':
        return 'assets/images/pico_4_ultra.jpg';
      default:
        return 'assets/images/unknown.jpg'; // Путь по умолчанию
    }
  }

  @override
  Widget build(BuildContext context) {
    double screenWidth = MediaQuery.of(context).size.width;

    // Устанавливаем количество карточек в зависимости от ширины экрана
    int crossAxisCount;
    if (screenWidth < 720) {
      crossAxisCount = 2; // Для маленьких экранов
    } else if (screenWidth < 1200) {
      crossAxisCount = 4;
    } else {
      crossAxisCount = 6; // Для больших экранов
    }


    // Сортируем устройства по номеру шлема
    _devicesList.sort((a, b) => int.parse(a['number']!).compareTo(int.parse(b['number']!)));

    return Scaffold(
      appBar: AppBar(
        title: const Text('ADB Device Connector'),
        actions: [
          IconButton(
            icon: const Icon(Icons.play_arrow),
            onPressed: () async {
              String? packageName = await showDialog<String>(
                context: context,
                builder:(BuildContext context) {
                  String? inputPackageName;
                  return AlertDialog(
                    title :Text('Введите имя пакета приложения'),
                    content :TextField(
                      onChanged :(value) {
                        inputPackageName = value;
                      },
                      decoration :InputDecoration(hintText :"com.example.app"),
                    ),
                    actions :<Widget>[
                      TextButton(child :Text('Отмена'), onPressed :() => Navigator.of(context).pop()),
                      TextButton(child :Text('Запустить на всех'),
                          onPressed :() {
                            if (inputPackageName != null && inputPackageName!.isNotEmpty) {
                              Navigator.of(context).pop(inputPackageName); // Возвращаем имя пакета
                            }
                          }),
                    ],
                  );
                },
              );

              if (packageName != null && packageName.isNotEmpty) {
                await _launchAppOnAllDevices(packageName); // Запускаем приложение на всех устройствах
              }
            },
          ),
          IconButton(
            icon: const Icon(Icons.upload_file),
            onPressed: _uploadApkAll,
          ),
          IconButton(
            icon: const Icon(Icons.link),
            onPressed: _launchUrlAll,
          ),
        ],
      ),
      body: SingleChildScrollView( // Оборачиваем в SingleChildScrollView для прокрутки
        child: Wrap( // Используем Wrap вместо Row
          spacing: 8.0, // Расстояние между карточками по горизонтали
          runSpacing: 8.0, // Расстояние между карточками по вертикали
          children: _devicesList.map((device) {
            return Padding( // Добавляем Padding для отступа в начале каждого элемента
              padding: const EdgeInsets.only(left: 8.0), // Отступ слева
              child: Container(
                width: (screenWidth / crossAxisCount) - 16, // Устанавливаем ширину карточки с учетом отступов
                child: IntrinsicHeight( // Используем IntrinsicHeight для равной высоты
                  child: Column(
                    children: [
                      Container(
                        padding: const EdgeInsets.all(8.0),
                        alignment: Alignment.center,
                        color: Colors.blueAccent,
                        child: Text(
                          'Helmet № ${device['number']}',
                          style: TextStyle(color: Colors.white, fontSize: 18),
                        ),
                      ),
                      Expanded( // Используем Expanded для того, чтобы изображение занимало оставшееся пространство
                        child: Container(
                          width: double.infinity,
                          child: Image.asset(
                            _getImageHelmetPath(device['model']!),
                            fit: BoxFit.cover,
                          ),
                        ),
                      ),
                      SizedBox(
                        height: 200, // Установите фиксированную высоту
                        child: Padding(
                          padding: const EdgeInsets.all(15.0),
                          child: Column(
                            mainAxisAlignment: MainAxisAlignment.start, // Элементы располагаются от начала
                            crossAxisAlignment: CrossAxisAlignment.center, // Центрируем содержимое по горизонтали
                            children: [
                              MouseRegion(
                                cursor: SystemMouseCursors.click,
                                child: GestureDetector(
                                  onTap: () {
                                    // Копируем текст серийного номера в буфер обмена
                                    Clipboard.setData(ClipboardData(text: device['real_sn'].toString()));
                                    ScaffoldMessenger.of(context).showSnackBar(
                                      SnackBar(
                                        content: Text('Скопировано: ${device['real_sn']}'),
                                        duration: Duration(seconds: 1), // Установите желаемую продолжительность
                                      ),
                                    );
                                  },
                                  child: AutoSizeText(
                                    'Serial Number: ${device['real_sn']}',
                                    style: TextStyle(fontSize: 14, color: Colors.black), // Начальный размер шрифта
                                    maxLines: 2, // Максимальное количество строк
                                    textAlign: TextAlign.center, // Центрируем текст
                                  ),
                                ),
                              ),
                              MouseRegion(
                                cursor: SystemMouseCursors.click,
                                child: GestureDetector(
                                  onTap: () {
                                    // Копируем текст IP-адреса в буфер обмена
                                    Clipboard.setData(ClipboardData(text: device['ip'].toString()));
                                    ScaffoldMessenger.of(context).showSnackBar(
                                      SnackBar(
                                        content: Text('Скопировано: ${device['ip']}'),
                                        duration: Duration(seconds: 1), // Установите желаемую продолжительность
                                      ),
                                    );
                                  },
                                  child: AutoSizeText(
                                    'IP Address: ${device['ip']}',
                                    style: TextStyle(fontSize: 14, color: Colors.black), // Начальный размер шрифта
                                    maxLines: 2,
                                    textAlign: TextAlign.center, // Центрируем текст
                                  ),
                                ),
                              ),
                              AutoSizeText(
                                'Battery Level: ${device['battery_level']}%',
                                style: TextStyle(fontSize: 14),
                                maxLines: 1,
                                textAlign: TextAlign.center,
                              ),
                              LinearProgressIndicator(
                                value: double.parse(device['battery_level'].toString()) / 100, // Уровень от 0.0 до 1.0
                                backgroundColor: Colors.grey[300],
                                valueColor: AlwaysStoppedAnimation<Color>(Colors.green), // Цвет заполненной части
                              ),
                              SizedBox(height: 8), // Отступ между уровнями
                              AutoSizeText(
                                'Right controller level: ${device['battery_r']}%',
                                style: TextStyle(fontSize: 14),
                                maxLines: 1,
                                textAlign: TextAlign.center,
                              ),
                              LinearProgressIndicator(
                                value: double.parse(device['battery_r'].toString()) / 100,
                                backgroundColor: Colors.grey[300],
                                valueColor: AlwaysStoppedAnimation<Color>(Colors.blue), // Цвет заполненной части
                              ),
                              SizedBox(height: 8), // Отступ между уровнями
                              AutoSizeText(
                                'Left Battery Level: ${device['battery_l']}%',
                                style: TextStyle(fontSize: 14),
                                maxLines: 1,
                                textAlign: TextAlign.center,
                              ),
                              LinearProgressIndicator(
                                value: double.parse(device['battery_l'].toString()) / 100,
                                backgroundColor: Colors.grey[300],
                                valueColor: AlwaysStoppedAnimation<Color>(Colors.red), // Цвет заполненной части
                              ),
                            ],
                          ),
                        ),
                      ),
                      Wrap(
                        spacing: 8.0, // Расстояние между кнопками по горизонтали
                        runSpacing: 8.0, // Расстояние между кнопками по вертикали
                        alignment: WrapAlignment.center, // Центрируем кнопки
                        children: [
                          IconButton(
                            icon: const Icon(Icons.camera),
                            onPressed: () => _startDeviceStreaming(device['serial_number']!),
                          ),
                          IconButton(
                            icon: const Icon(Icons.home),
                            onPressed: () => _launchHome(device['serial_number']!),
                          ),
                          IconButton(
                            icon: const Icon(Icons.upload_file),
                            onPressed: () => _uploadApk(device['serial_number']!),
                          ),
                          IconButton(
                            icon: const Icon(Icons.link),
                            onPressed: () => _launchUrl(device['serial_number']!),
                          ),
                          IconButton(
                            icon: device['sensor'] == '1'
                                ? const Icon(Icons.sensors_off) // Заполненная иконка, если сенсор включен
                                : const Icon(Icons.sensors_outlined), // Обычная иконка, если сенсор выключен
                            onPressed: () => _toggleSensorState(device['serial_number']!),
                          ),
                          IconButton(
                            icon: const Icon(Icons.play_arrow), // Кнопка для открытия диалога запуска приложения
                            onPressed: () => _showLaunchAppDialog(device['serial_number']!),
                          ),
                          IconButton(
                            icon: const Icon(Icons.numbers),
                            onPressed: () async {
                              int? helmetNumber = await showDialog<int>(
                                context: context,
                                builder:(BuildContext context) {
                                  int? number;
                                  return AlertDialog(
                                    title :Text('Введите номер шлема'),
                                    content :TextField(
                                      keyboardType :TextInputType.number,
                                      onChanged :(value) {
                                        number = int.tryParse(value);
                                      },
                                    ),
                                    actions :<Widget>[
                                      TextButton(child :Text('Отмена'), onPressed :() => Navigator.of(context).pop()),
                                      TextButton(child :Text('Привязать'), onPressed :() => Navigator.of(context).pop(number)),
                                    ],
                                  );
                                },
                              );

                              if (helmetNumber != null) {
                                await _bindHelmetNumber(device['real_sn']!, helmetNumber);
                              }
                            },
                          ),
                        ],
                      )
                    ],
                  ),
                ),
              ),
            );
          }).toList(),
        ),
      ),
    );
  }
}