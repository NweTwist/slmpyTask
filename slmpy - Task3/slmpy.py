# -*- coding: utf-8 -*-
"""
Created on Sun Dec 06 20:14:02 2015

@author: Sebastien M. Popoff

"""

try:
    import wx
except ImportError:
    raise ImportError("Для работы программы требуется модуль wxPython.")
import threading
import numpy as np
import time
import socket
import struct
import bz2
import zlib
import gzip


EVT_NEW_IMAGE = wx.PyEventBinder(wx.NewEventType(), 0)

class ImageEvent(wx.PyCommandEvent):
    def __init__(self, eventType=EVT_NEW_IMAGE.evtType[0], id=0):
        wx.PyCommandEvent.__init__(self, eventType, id)
        self.img = None
        self.color = False
        self.oldImageLock = None
        self.eventLock = None


class SLMframe(wx.Frame):
    
    def __init__(self, 
                 monitor, 
                 isImageLock,
                 alwaysTop):
        
        style = wx.DEFAULT_FRAME_STYLE
        if alwaysTop:
            style = style | wx.STAY_ON_TOP
        self.isImageLock = isImageLock
        self.SetMonitor(monitor)
        super().__init__(None,
                         -1,
                         'Окно SLM',
                         pos = (self._x0, self._y0), 
                         size = (self._resX, self._resY),
                         style = style
                        ) 
        
        self.Window = SLMwindow(self, 
                                isImageLock = isImageLock,
                                res = (self._resX, self._resY)
                               )
        self.Show()
        
        self.Bind(EVT_NEW_IMAGE, self.OnNewImage)
        self.ShowFullScreen(not self.IsFullScreen(), wx.FULLSCREEN_ALL)
        self.SetFocus()
        
    def SetMonitor(self, monitor: int):
        if (monitor < 0 or monitor > wx.Display.GetCount()-1):
            raise ValueError('Неверный номер монитора (монитор %d).' % monitor)
        self._x0, self._y0, self._resX, self._resY = wx.Display(monitor).GetGeometry()
        
    def OnNewImage(self, event):
        self.Window.UpdateImage(event)
        
    
    def Quit(self):
        wx.CallAfter(self.Destroy)
        
        
class SLMwindow(wx.Window):
    
    def __init__(self,  *args, **kwargs):
        self.isImageLock = kwargs.pop('isImageLock')
        self.res = kwargs.pop('res')
        kwargs['style'] = kwargs.setdefault('style', wx.NO_FULL_REPAINT_ON_RESIZE) | wx.NO_FULL_REPAINT_ON_RESIZE
        super().__init__(*args, **kwargs)
        
        # скрыть курсор
        cursor = wx.StockCursor(wx.CURSOR_BLANK)
        self.SetCursor(cursor) 
        
        self.img = wx.Image(*self.res)
        self._Buffer = wx.Bitmap(*self.res)
        self.Bind(wx.EVT_SIZE, self.OnSize)
        self.Bind(EVT_NEW_IMAGE, self.UpdateImage)
        self.Bind(wx.EVT_PAINT,self.OnPaint)
        
        self.OnSize(None)
        
    def OnPaint(self, event):
        self._Buffer = self.img.ConvertToBitmap()
        dc = wx.BufferedPaintDC(self, self._Buffer)
#         dc = wx.PaintDC(self)
#         dc.DrawBitmap(self._Buffer,0,0)
 
    def OnSize(self, event):
        # Инициализация буфера происходит здесь, чтобы убедиться, что буфер всегда
        # имеет тот же размер, что и окно
        Size = self.GetClientSize()

        # Создаем новый внеэкранный битмап: этот битмап всегда будет содержать
        # текущее изображение, поэтому его можно использовать для сохранения изображения
        # в файл или для других целей
        self._Buffer = wx.Bitmap(*self.res)
        
    def UpdateImage(self, event):
        self.eventLock = event.eventLock
        self.img = event.img
        self.Refresh(eraseBackground=False)
        
        self.ReleaseEventLock()
        
    def ReleaseEventLock(self):
        if self.eventLock:
            if self.eventLock.locked():
                self.eventLock.release()

    
class Client():
    """Класс клиента для взаимодействия с slmPy, запущенным на удаленном сервере."""
    def __init__(self):
        pass

    def start(self, 
              server_address: str, 
              port: int = 9999, 
              compression: str = 'zlib',
              compression_level: int = -1,
              wait_for_reply: bool = True
             ):
        """
        Параметры
        ----------
        server_address : str
            Адрес или сетевое имя сервера для подключения.
            Пример: '192.168.0.100' / 'localhost'
        port : int, по умолчанию 9999
            Номер порта прослушивающего сокета на сервере.
        compression : str, по умолчанию 'zlib'
            Алгоритм сжатия для использования перед отправкой данных клиенту.
            Может быть 'zlib', 'gzip', 'bz2' или None для отсутствия сжатия.
            Если сжатие не распознано, сжатие не выполняется.
        compression_level: int, по умолчанию -1
            Уровень сжатия. Зависит от алгоритма сжатия.
        wait_for_reply: bool, по умолчанию True
            Если True, ожидает подтверждения от сервера перед возвратом при вызове sendArray.
            Сервер должен использовать аргумент `comfirm` в `listen_port()` с тем же значением.
            Будьте осторожны, некоторые изображения могут быть пропущены!
        """
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.compression = compression
        if compression_level == -1 and compression == 'bz2':
            compression_level = 9
        self.compression_level = compression_level
        self.wait_for_reply = wait_for_reply
        try:
            self.client_socket.connect((server_address, port))
            print(f'Подключено к {server_address} на порту {port}')
        except socket.error as e:
            print(f'Ошибка подключения к {server_address} на порту {port}: {e}')
            return

    def _send_numpy_array(self, np_array):
        """
        Отправляет массив numpy в подключенный сокет.
        
        Параметры
        ----------
        np_array : array_like
            Массив numpy для отправки в прослушивающий сокет.
        """
        data = np_array.tobytes()
        
        if self.compression == 'bz2':
             data = bz2.compress(data, 
                                 compresslevel = self.compression_level)
        elif self.compression == 'zlib':
             data = zlib.compress(data, 
                                  level = self.compression_level)
        elif self.compression == 'gzip':
             data = gzip.compress(data, 
                                  compresslevel = self.compression_level)

        # Сначала отправляем длину сообщения
        # используем "i" потому что "L" для unsigned long не имеет одинакового
        # размера на разных системах (4 на raspberry pi!)
        message_size = struct.pack("i", len(data)) 
        
        # Затем отправляем данные
        self.client_socket.sendall(message_size + data)
        
    def sendArray(self, 
                  arr: np.ndarray, 
                  timeout: float = 10,
                  retries: int = 2):
        """
        Отправляет массив numpy в подключенный сокет.
        
        Параметры
        ----------
        arr : array_like
            Массив numpy для отправки на сервер.
        timeout : float, по умолчанию 10
            Таймаут в секундах.
        retries : int, по умолчанию 2
            Количество попыток отправки данных при возникновении ошибки.
        """
        if not isinstance(arr, np.ndarray):
            print('Неверное изображение numpy')
            return
        if not arr.dtype == np.uint8:
            print('Массив numpy должен быть типа uint8')


        for retry in range(retries):
            self._send_numpy_array(arr)
            t0 = time.time()
            if retry:
                print('Повторная попытка')
            if self.wait_for_reply:
                while True:
                    buffer = self.client_socket.recv(128)
                    if buffer and buffer.decode() == 'done':
                        print('Данные переданы')
                        return 1
                    elif buffer and buffer.decode() == 'err':
                        print('Ошибка. Данные не переданы')
                        print('Неверный размер изображения?')
                        break
                    elif time.time()-t0 > timeout:
                        print('Достигнут таймаут.')
                        break
            else:
                return 1
        else:
            return -1
        
    def close(self):
        self.client_socket.shutdown(1)
        self.client_socket.close()
        
class SLMDisplay():
    """Основной класс для управления дисплеем SLM."""
    _app = None
    _app_initialized = False
    _instances = []
    
    def __init__(self,
                 monitor = 1, 
                 isImageLock = False,
                 alwaysTop = False):
        """
        Инициализация дисплея SLM.
        
        Параметры
        ----------
        monitor : int, по умолчанию 1
            Номер монитора для использования в качестве дисплея SLM.
        isImageLock : bool, по умолчанию False
            Если True, изображение будет заблокировано для предотвращения обновлений во время отображения.
        alwaysTop : bool, по умолчанию False
            Если True, окно SLM всегда будет оставаться поверх других окон.
        """
        if not SLMDisplay._app_initialized:
            SLMDisplay._app = wx.App()
            SLMDisplay._app_initialized = True
            
        self.monitor = monitor
        self.isImageLock = isImageLock
        self.alwaysTop = alwaysTop
        self.frame = None
        self.videoThread = None
        self._lock = threading.Lock()
        
        # Добавляем этот экземпляр в список активных экземпляров
        SLMDisplay._instances.append(self)
        
        # Инициализируем дисплей
        self._init_display()
        
    def _init_display(self):
        """Инициализация окна дисплея и потока видео."""
        self.frame = SLMframe(self.monitor, self.isImageLock, self.alwaysTop)
        self.videoThread = videoThread(self)
        self.videoThread.start()
        
    def updateArray(self, array, sleep = 0.2):
        """
        Обновление отображаемого массива.
        
        Параметры
        ----------
        array : array_like
            Массив для отображения.
        sleep : float, по умолчанию 0.2
            Время ожидания между обновлениями.
        """
        if not isinstance(array, np.ndarray):
            print('Неверное изображение numpy')
            return
        if not array.dtype == np.uint8:
            print('Массив numpy должен быть типа uint8')
            return
            
        with self._lock:
            if self.videoThread:
                self.videoThread.updateImage(array)
                time.sleep(sleep)
                
    def close(self):
        """Закрытие дисплея SLM и очистка ресурсов."""
        if self in SLMDisplay._instances:
            SLMDisplay._instances.remove(self)
            
        if self.videoThread:
            self.videoThread.stop()
            self.videoThread = None
            
        if self.frame:
            self.frame.Quit()
            self.frame = None
            
        # Если это был последний экземпляр, очищаем wx приложение
        if not SLMDisplay._instances and SLMDisplay._app_initialized:
            SLMDisplay._app.Destroy()
            SLMDisplay._app_initialized = False
            
    def getSize(self):
        """Получение размера дисплея SLM."""
        return self.frame._resX, self.frame._resY

class videoThread(threading.Thread):
    """Поток для обработки обновлений видео."""
    def __init__(self, parent, autoStart=True):
        threading.Thread.__init__(self)
        self.parent = parent
        self._stop_event = threading.Event()
        self._image_lock = threading.Lock()
        self._current_image = None
        self._new_image_event = threading.Event()
        
        if autoStart:
            self.start()
            
    def run(self):
        """Основной цикл потока."""
        while not self._stop_event.is_set():
            if self._new_image_event.wait(timeout=0.1):
                with self._image_lock:
                    if self._current_image is not None:
                        event = ImageEvent()
                        event.img = wx.ImageFromBuffer(
                            self._current_image.shape[1],
                            self._current_image.shape[0],
                            self._current_image.tobytes()
                        )
                        event.eventLock = threading.Lock()
                        event.eventLock.acquire()
                        wx.PostEvent(self.parent.frame, event)
                self._new_image_event.clear()
                
    def updateImage(self, image):
        """Обновление текущего изображения."""
        with self._image_lock:
            self._current_image = image.copy()
        self._new_image_event.set()
        
    def stop(self):
        """Остановка потока."""
        self._stop_event.set()
        self.join()
