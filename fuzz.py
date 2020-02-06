#!/usr/bin/python3

from enum import Enum
from math import ceil, floor
from os import listdir
from os.path import dirname, isfile, splitext
from queue import Empty, Queue
from select import select
from socket import socket, AF_INET, SOCK_DGRAM
from subprocess import Popen, PIPE
from threading import currentThread, Thread, Timer
from time import sleep, time

from Adafruit_ADS1x15 import ADS1115
from adafruit_rgb_display import color565
from adafruit_rgb_display.ili9341 import ILI9341
from board import SCK, MOSI, MISO, D8, D24, D25
from busio import SPI
from digitalio import DigitalInOut
from mpd import MPDClient
from PIL import Image, ImageDraw, ImageFont 


##
# Logger
##

class Logger(object):

    def log_info(self, message):
        print("[INFO | %s] %s" % (currentThread().getName(), message))

    def log_error(self, message):
        print("[WARNING | %s] %s" % (currentThread().getName(), message))


##
# Theme
##

class Theme(object):

    def __init__(self):
        self.fontPath = "Inconsolata-Regular.ttf"
        self.mainColor = 0x00ff00
        self.volumeColors = [0x00ff00, 0x00ffff, 0x0000ff]

    def get_font(self, size):
        return ImageFont.truetype(self.fontPath, size)


##
# Display Driver
##

class DisplayDriver(object):

    def __init__(self, logger):
        self._logger = logger
        self._logger.log_info("Initializing display")
        spi = SPI(clock=SCK, MOSI=MOSI, MISO=MISO)
        self._driver = ILI9341(spi, cs=DigitalInOut(D8), dc=DigitalInOut(D24), rst=DigitalInOut(D25))
        self._driver.fill(0)

    def get_width(self):
        return self._driver.width

    width = property(get_width)

    def get_height(self):
        return self._driver.height

    height = property(get_height)

    def display(self, image, x=0, y=0):
        self._logger.log_info("Displaying image at (%d,%d)" % (x, y))
        self._driver.image(image, x=x, y=y)


##
# Serial Queue
##

class SerialQueue(object):

    def __init__(self, name):
        self._queue = Queue()
        Thread(target=self._run, name="SerialQueue %s" % name).start()

    def _run(self):
        while True:
            self._queue.get()()
            self._queue.task_done()

    def run_sync(self, task):
        # This isn't quite exact as there could be other tasks added to the queue before the
        # call to join but (hopefully) it'll be enough for our needs here
        self.run_async(task)
        self._queue.join()

    def run_async(self, task):
        self._queue.put(task)


##
# App / Widget Kit
##

class App(object):

    def __init__(self, controller):
        self.controllers = [controller]
        self._queue = SerialQueue("main")

    def run(self):
        self.controllers[-1].will_appear()
        Thread(target=self._iterate).start()

    def _iterate(self):
        while True:
            self._queue.run_sync(self._drawAndDisplay)
            _, _, _ = select([], [], [], 1)

    def _drawAndDisplay(self):
        self.controllers[-1].window.draw()
        self.controllers[-1].window.display()

    def push(self, controller):
        self._queue.run_async(lambda: self._push(controller))

    def _push(self, controller):
        if self.controllers:
            self.controllers[-1].will_disappear()
        self.controllers.append(controller)
        controller.will_appear()

    def pop(self):
        self._queue.run_async(self._pop)

    def _pop(self):
        current = self.controllers.pop()
        current.will_disappear()
        if self.controllers:
            self.controllers[-1].will_appear()


class Controller(object):

    def __init__(self, window, navigator, logger):
        self.window = window
        self.navigator = navigator
        self.logger = logger

    def push(self, controller):
        self.navigator.push(controller)

    def pop(self):
        self.navigator.pop()

    def will_appear(self):
        self.logger.log_info('%s will appear' % self)

    def will_disappear(self):
        self.logger.log_info('%s will disappear' % self)
        self.window.wasDisplayedOnce = False


class Window(object):

    def __init__(self, theme, driver, logger):
        self.theme = theme
        self._driver = driver
        self._logger = logger
        self._layer = Image.new("RGB", (driver.width, driver.height), "black")
        self._context = ImageDraw.Draw(self._layer)
        self._widgets = []
        self._dirtyFrames = set()
        self.wasDisplayedOnce = False

    def add_widget(self, widget):
        self._widgets.append(widget)

    def draw(self):
        t1 = time()
        self._draw(self._widgets)
        self._logger.log_info("Drawing of window %s finished in %.3fs" % (self, time() - t1))
            

    def _draw(self, widgets):
        for widget in widgets:
            if widget.hidden:
                continue
            if widget.needsRedraw:
                self._logger.log_info("Drawing widget %s" % widget)
                widget.draw(self._layer, self._context)
                self._dirtyFrames.add(widget.frame)
            else:
                self._draw(widget.children)

    def display(self):
        # The lower boundary for displaying even small images is around 0.05s while refreshing the whole display
        # takes around 0.25s. Consequently, when at least 5 subareas have to be re-displayed, a full display
        # refresh is faster (or at least equal in performance).
        if not self.wasDisplayedOnce or len(self._dirtyFrames) > 4:
            t1 = time()
            self._driver.display(self._layer)
            self._logger.log_info("Display of full layer of window %s finished in %.3fs" % (self, time() - t1))
        else:
            for frame in self._dirtyFrames:
                t1 = time()
                self._driver.display(self._layer.crop(frame.corners), x=frame.x0, y=frame.y0)
                self._logger.log_info("Display of dirty frame %s of window %s finished in %.3fs" % (frame, self, time() - t1))
        self._dirtyFrames.clear()
        self.wasDisplayedOnce = True


class Frame(object):

    def __init__(self, x0, y0, x1, y1):
        self.x0 = x0
        self.x1 = x1
        self.y0 = y0
        self.y1 = y1

        self.width = self.x1 - self.x0 + 1
        self.height = self.y1 - self.y0 + 1

        self.corners = [self.x0, self.y0, self.x1, self.y1]

    def __str__(self):
        return "%s" % self.corners


class Widget(object):

    def __init__(self, frame):
        self.frame = frame
        self.wasDrawnOnce = False
        self.needsRedraw = True
        self.hidden = False
        self.children = []

    def draw(self, layer, context):
        self.needsRedraw = False
        if self.wasDrawnOnce:
            context.rectangle(self.frame.corners, fill="black")
        else:
            self.wasDrawnOnce = True
        for widget in self.children:
            widget.draw(layer, context)


class TextAlignment(Enum):

    LEFT = 1
    RIGHT = 2
    CENTER = 3


class TextWidget(Widget):

    def __init__(self, frame, font, color, text="", alignment=TextAlignment.LEFT):
        self._text = text
        self._font = font
        self._color = color
        self._alignment = alignment
        super().__init__(frame)

    def get_text(self):
        return self._text

    def set_text(self, text):
        self._text = text or ""
        self.needsRedraw = True

    text = property(get_text, set_text)

    def draw(self, layer, context):
        super().draw(layer, context)

        if self._alignment == TextAlignment.LEFT:
            x = self.frame.x0
        elif self._alignment == TextAlignment.RIGHT:
            size = context.textsize(self._text, self._font)
            x = self.frame.x1 + 1 - size[0]
        elif self._alignment == TextAlignment.CENTER:
            size = context.textsize(self._text, self._font)
            x = self.frame.x0 + round((self.frame.width - size[0]) / 2.0)

        context.text((x, self.frame.y0), self._text, font=self._font, fill=self._color)


class HRule(Widget):

    def __init__(self, y, width, color):
        self._color = color
        super().__init__(Frame(0, y, width - 1, y))

    def draw(self, layer, context):
        super().draw(layer, context)
        context.rectangle(self.frame.corners, fill=self._color)


class ImageWidget(Widget):

    def __init__(self, frame, image = None):
        super().__init__(frame)
        self.image = image

    def get_image(self):
        return self._image

    def set_image(self, image):
        self._image = image
        if self._image:
            self._image.thumbnail((self.frame.width, self.frame.height))
        self.needsRedraw = True

    image = property(get_image, set_image)

    def draw(self, layer, context):
        super().draw(layer, context)
        if self._image:
            x = self.frame.x0 + round((self.frame.width - self._image.width) / 2)
            y = self.frame.y0 + round((self.frame.height - self._image.height) / 2)
            layer.paste(self._image, (x, y))


class ProgressBar(Widget):

    def __init__(self, frame, progress, text, font, color):
        super().__init__(frame)
        self.progress = progress
        self._text = text
        self._font = font
        self._color = color

    def get_progress(self):
        return self._progress

    def set_progress(self, progress):
        self._progress = min(max(0, progress), 100)
        self.needsRedraw = True

    progress = property(get_progress, set_progress)

    def get_text(self):
        return self._text

    def set_text(self, text):
        self._text = text
        self.needsRedraw = True

    text = property(get_text, set_text)

    def draw(self, layer, context):
        super().draw(layer, context)

        context.rectangle(self.frame.corners, outline=self._color)

        if self._progress > 0:
            offset = self.frame.x0 + 1 + round(self._progress / 100 * (self.frame.x1 - 1 - self.frame.x0 - 1))
            context.rectangle([self.frame.x0 + 1, self.frame.y0 + 1, offset, self.frame.y1 -1], fill=self._color)
        
        size = context.textsize(self._text, self._font)
        x = self.frame.x0 + round((self.frame.width - size[0]) / 2.0)
        y = self.frame.y0 + round((self.frame.height - size[1]) / 2.0)
        context.text((x, y), self._text, font=self._font, fill=0xffffff)


class VolumeBar(Widget):

    def __init__(self, frame, color, volumeColors, volume=0):
        self.volume = volume
        self._color = color
        self._volumeColors = volumeColors
        super().__init__(frame)

    def get_volumne(self):
        return self._volume

    def set_volume(self, volume):
        self._volume = min(max(0, volume), 100)
        self.needsRedraw = True

    volume = property(get_volumne, set_volume)

    def draw(self, layer, context):
        super().draw(layer, context)

        context.rectangle(self.frame.corners, outline=self._color)

        if self._volume == 0:
            return

        inset = 3
        maxHeight = self.frame.height - 2 * inset
        minY = self.frame.y0 + inset + round((1 - self._volume / 100) * (maxHeight - 1))

        spacing = 1
        segmentHeight = 3

        y = self.frame.y1 - inset

        while True:
            segmentOffset = y - segmentHeight + 1
            if segmentOffset < minY:
                break

            ratio = (self.frame.y1 - inset - segmentOffset + 1) / (self.frame.height - 2 * inset)
            color = self._volumeColors[ceil(ratio * len(self._volumeColors)) - 1]

            context.rectangle([(self.frame.x0 + inset, segmentOffset), (self.frame.x1 - inset, y)], fill=color)
            y -= spacing + segmentHeight

        # Due to the rounding the last segment will usually be smaller in height. In reality this should
        # rarely matter though because you'd hardly listen at full volume.
        if self._volume == 100:
            context.rectangle([
                (self.frame.x0 + inset, self.frame.y0 + inset),
                (self.frame.x1 - inset, max(self.frame.y0 + inset, y))], fill=self._volumeColors[-1])


class PlayPauseIcon(Widget):

    def __init__(self, frame, color, play):
        self._color = color
        self._play = play
        super().__init__(frame)

    def get_play(self):
        return self._play

    def set_play(self, play):
        self._play = play
        self.needsRedraw = True

    play = property(get_play, set_play)

    def draw(self, layer, context):
        super().draw(layer, context)

        size = min(self.frame.width, self.frame.height)

        xOffset = round((self.frame.width - size) / 2)
        yOffset = round((self.frame.height - size) / 2)

        x0 = self.frame.x0 + xOffset
        x1 = self.frame.x1 - xOffset
        y0 = self.frame.y0 + yOffset
        y1 = self.frame.y1 - yOffset

        if self._play:
            self._draw_play(context, x0, x1, y0, y1)
        else:
            self._draw_pause(context, x0, x1, y0, y1)
    
    def _draw_play(self, context, x0, x1, y0, y1):
        context.polygon([
            (x0, y0),
            (x1, round((self.frame.y1 + self.frame.y0) / 2)),
            (x0, y1)], fill=self._color)

    def _draw_pause(self, context, x0, x1, y0, y1):
        barWidth = round((x1 - x0 + 1) / 5)
        center = round((x1 + x0) / 2)

        context.rectangle([
            (center - barWidth, y0),
            (center - 2 * barWidth + 1, y1)], fill=self._color)
        context.rectangle([
            (center + barWidth, y0),
            (center + 2 * barWidth - 1, y1)], fill=self._color)


class PreviousNextIcon(Widget):

    def __init__(self, frame, color, previous):
        self._color = color
        self._previous = previous
        super().__init__(frame)

    def get_previous(self):
        return self._previous

    def set_previous(self, previous):
        self._previous = previous
        self.needsRedraw = True

    previous = property(get_previous, set_previous)

    def draw(self, layer, context):
        super().draw(layer, context)

        width = min(self.frame.width, 2 * self.frame.height)
        height = round(width / 2)

        xOffset = round((self.frame.width - width) / 2)
        yOffset = round((self.frame.height - height) / 2)

        x0 = self.frame.x0 + xOffset
        x1 = self.frame.x1 - xOffset
        y0 = self.frame.y0 + yOffset
        y1 = self.frame.y1 - yOffset

        barWidth = round(width / 10)
        triangleWidth = round((width - barWidth) / 2)
        if barWidth + 2 * triangleWidth < width:
            barWidth += 1

        if self._previous:
            self._draw(context, x0, x1, y0, y1, barWidth, triangleWidth, lambda x: x)
        else:
            self._draw(context, x0, x1, y0, y1, barWidth, triangleWidth, lambda x: x0 + x1 - x)

    def _draw(self, context, x0, x1, y0, y1, barWidth, triangleWidth, transform):
        context.polygon([
            (transform(x1), y0),
            (transform(x1 - triangleWidth + 1), round((y1 + y0) / 2)),
            (transform(x1), y1)], fill=self._color)
        context.polygon([
            (transform(x1 - triangleWidth), y0),
            (transform(x0 + barWidth), round((y1 + y0) / 2)),
            (transform(x1 - triangleWidth), y1)], fill=self._color)
        context.rectangle([
            (transform(x0), y0),
            (transform(x0 + barWidth - 1), y1)], fill=self._color)


class ToolbarButtonType(Enum):

    PLAY_PAUSE = 1
    PREVIOUS = 2
    NEXT = 3


class ToolbarButton(Widget):

    def __init__(self, button_type, frame, theme, text=""):
        super().__init__(frame)

        self.label = TextWidget(
            frame=Frame(frame.x0, frame.y0, frame.x1, frame.y0 + 16),
            text=text,
            font=theme.get_font(14),
            color=theme.mainColor,
            alignment=TextAlignment.CENTER)
        self.children.append(self.label)

        iconFrame = Frame(frame.x0, frame.y0 + 22, frame.x1, frame.y1)

        if button_type == ToolbarButtonType.PLAY_PAUSE:
            self.icon = PlayPauseIcon(frame=iconFrame, color=theme.mainColor, play=False)
        elif button_type == ToolbarButtonType.PREVIOUS:
            self.icon = PreviousNextIcon(frame=iconFrame, color=theme.mainColor, previous=True)
        elif button_type == ToolbarButtonType.NEXT:
            self.icon = PreviousNextIcon(frame=iconFrame, color=theme.mainColor, previous=False)

        self.children.append(self.icon)


##
# Windows
##

class PlayingWindow(Window):

    def __init__(self, theme, driver, logger):
        super().__init__(theme, driver, logger)

        self.ipLabel = TextWidget(
            frame=Frame(0, 0, 119, 16),
            font=self.theme.get_font(14),
            color=self.theme.mainColor)
        self.add_widget(self.ipLabel)

        self.ssidLabel = TextWidget(
            frame=Frame(120, 0, 239, 16),
            font=self.theme.get_font(14),
            color=self.theme.mainColor,
            alignment=TextAlignment.RIGHT)
        self.add_widget(self.ssidLabel)

        self.add_widget(HRule(17, 240, theme.mainColor))

        self.cover = ImageWidget(frame=Frame(54, 28, 153, 127))
        self.add_widget(self.cover)

        self.artistLabel = TextWidget(
            frame=Frame(10, 138, 198, 156),
            font=self.theme.get_font(16),
            color=self.theme.mainColor,
            alignment=TextAlignment.CENTER)
        self.add_widget(self.artistLabel)

        self.titleLabel = TextWidget(
            frame=Frame(10, 162, 198, 180),
            font=self.theme.get_font(16),
            color=self.theme.mainColor,
            alignment=TextAlignment.CENTER)
        self.add_widget(self.titleLabel)

        self.albumLabel = TextWidget(
            frame=Frame(10, 186, 198, 202),
            font=self.theme.get_font(16),
            color=self.theme.mainColor,
            alignment=TextAlignment.CENTER)
        self.add_widget(self.albumLabel)

        self.progressBar = ProgressBar(
            frame=Frame(10, 208, 198, 226),
            progress=0,
            text="",
            font=self.theme.get_font(14),
            color=self.theme.mainColor)
        self.add_widget(self.progressBar)

        self.volumeBar = VolumeBar(
            frame=Frame(209, 23, 239, 273),
            color=self.theme.mainColor,
            volumeColors=self.theme.volumeColors)
        self.add_widget(self.volumeBar)

        self.add_widget(HRule(279, 240, theme.mainColor))

        self.previousButton = ToolbarButton(
            button_type=ToolbarButtonType.PREVIOUS,
            frame=Frame(0, 280, 79, 319),
            theme=self.theme,
            text="Previous")
        self.add_widget(self.previousButton)

        self.playPauseButton = ToolbarButton(
            button_type=ToolbarButtonType.PLAY_PAUSE,
            frame=Frame(80, 280, 159, 319),
            theme=self.theme,
            text="Pause")
        self.add_widget(self.playPauseButton)

        self.nextButton = ToolbarButton(
            button_type=ToolbarButtonType.NEXT,
            frame=Frame(160, 280, 239, 319),
            theme=self.theme,
            text="Next")
        self.add_widget(self.nextButton)


class PlayingWindowController(Controller):

    def __init__(self, theme, driver, navigator, logger, network, mpdMonitor, mpdService):
        super().__init__(PlayingWindow(theme, driver, logger), navigator, logger)

        self.theme = theme
        self.driver = driver
        self.navigator = navigator
        self.logger = logger
        self.network = network
        self.mpdMonitor = mpdMonitor
        self.mpdService = mpdService

        self.window.ipLabel.text = network.ip
        self.window.ssidLabel.text = network.ssid

        self._progressTimer = None

        mpdMonitor.mixerListeners.append(self)
        mpdMonitor.playerListeners.append(self)

    def __del__(self):
        self.mpdMonitor.mixerListeners.remove(self)
        self.mpdMonitor.playerListeners.remove(self)

    def will_appear(self):
        super().will_appear()

        self._update_current_song()
        self._update_volume()
        self._update_state_and_progress()

        self.mpdMonitor.start()

        controller = LibraryWindowController(self.theme, self.driver, self.navigator, self.logger, self.mpdService)
        Timer(3, lambda: self.navigator.push(controller)).start()

    def will_disappear(self):
        super().will_disappear()
        self.mpdMonitor.stop()

    def on_mixer_changed(self):
        self._update_volume()

    def on_player_changed(self):
        self._update_current_song()
        self._update_state_and_progress()

    def _update_current_song(self):
        song = self.mpdMonitor.currentSong
        if song:
            self.window.cover.image = self._load_cover(song.path)
            self.window.artistLabel.text = song.artist
            self.window.titleLabel.text = song.title
            self.window.albumLabel.text = "%s (%s)" % (song.album, song.date) if song.album else None
            self.window.progressBar.hidden = False
        else:
            self.window.cover.image = None
            self.window.artistLabel.text = None
            self.window.titleLabel.text = None
            self.window.albumLabel.text = None
            self.window.progressBar.hidden = True

    def _load_cover(self, path):
        if not path:
            return None

        fullPath = path
        if not isfile(fullPath):
            fullPath = "/mnt/%s" % path
            if not isfile(fullPath):
                self.logger.log_error("Could not find cover for %s" % path)
                return None

        directory = dirname(fullPath)
        
        for element in listdir(directory):
            elementPath = "%s/%s" % (directory, element)
            if isfile(elementPath) and splitext(element)[0] == "cover":
                try:
                    cover = Image.open(elementPath)
                    self.logger.log_info("Loaded cover from %s" % elementPath)
                    return cover
                except IOError:
                    self.logger.log_error("Could not load cover from %s" % elementPath)

        self.logger.log_error("Could not find cover for %s" % path)

    def _update_volume(self):
        self.window.volumeBar.volume = self.mpdMonitor.volume

    def _update_state_and_progress(self):
        state = self.mpdMonitor.state
        if state == MpdState.PLAYING:
            self._start_progress_timer(self.mpdMonitor.elapsed, self.mpdMonitor.duration)
            self.window.playPauseButton.icon.play = False
            self.window.playPauseButton.label.text = "Pause"
        elif state == MpdState.PAUSED or state == MpdState.STOPPED:
            self._stop_progress_timer()
            self.window.playPauseButton.icon.play = True
            self.window.playPauseButton.label.text = "Play"

    def _start_progress_timer(self, elapsed, duration):
        self._stop_progress_timer()

        if not elapsed or not duration:
            self.window.progressBar.progress = 0
            return

        step = 10
        exactProgress = elapsed / duration * 100
        currentMark = round(exactProgress / step) * step

        self.window.progressBar.progress = currentMark

        if currentMark == 100:
            return

        nextMark = currentMark + step
        interval = duration * nextMark / 100 - elapsed

        self._progressTimer = Timer(interval, lambda: self._start_progress_timer(elapsed + interval, duration))
        self._progressTimer.start()

    def _stop_progress_timer(self):
        if not self._progressTimer:
            return
        self._progressTimer.cancel()
        self._progressTimer = None


class LibraryWindow(Window):

    def __init__(self, theme, driver, logger):
        super().__init__(theme, driver, logger)

        self.titleLabel = TextWidget(
            frame=Frame(0, 0, 119, 22),
            font=self.theme.get_font(20),
            text="Library",
            color=self.theme.mainColor)
        self.add_widget(self.titleLabel)


class LibraryWindowController(Controller):

    def __init__(self, theme, driver, navigator, logger, mpdService):
        super().__init__(LibraryWindow(theme, driver, logger), navigator, logger)
        self.mpdService = mpdService

    def will_appear(self):
        super().will_appear()
        self.mpdService.fetch_artists(lambda artists: print(artists))
        Timer(3, self.navigator.pop).start()


##
# App
##

class PlayerApp(App):

    def __init__(self, theme, driver, logger, network, mpdMonitor, mpdService):
        super().__init__(PlayingWindowController(theme, driver, self, logger, network, mpdMonitor, mpdService))


##
# Network Service
##

class NetworkService(object):

    def __init__(self, logger):
        self.logger = logger
        self._ip = None
        self._ipTimestamp = None
        self._ssid = None
        self._ssidTimestamp = None

    def get_ip(self):
        if not self._ipTimestamp or time() - self._ipTimestamp > 60:
            self._ip = self._get_ip()
        return self._ip

    def _get_ip(self):
        self.logger.log_info("Determining current IP address")
        self._ipTimestamp = time()
        s = socket(AF_INET, SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except:
            return "127.0.0.1"
        finally:
            s.close()

    ip = property(get_ip)

    def get_ssid(self):
        if not self._ssidTimestamp or time() - self._ssidTimestamp > 60:
            self._ssid = self._get_ssid()
        return self._ssid

    def _get_ssid(self):
        self.logger.log_info("Determining current SSID")
        self._ssidTimestamp = time()
        p = Popen(["iwgetid", "-r"], stdout = PIPE)
        output, error = p.communicate()
        if p.returncode == 0:
            return output.decode('utf-8').strip()
        else:
            self.logger.log_error(error)

    ssid = property(get_ssid)


##
# MPD Service
##

class MpdService(object):

    def __init__(self, logger, host="localhost", port=6600):
        self._logger = logger
        self._client = MPDClient()
        self._queue = SerialQueue("MPD")
        self._queue.run_async(lambda: self._client.connect(host, port))

    def __del__(self):
        self._queue.run_async(lambda: self._client.disconnect())

    def change_volume(self, value):
        self._logger.log_info("Changing volume to %i%%" % value)
        self._queue.run_async(lambda: self._client.setvol(value))

    def fetch_artists(self, on_finished):
        self._logger.log_info("Fetching artists")
        self._queue.run_async(lambda: on_finished(self._client.list("albumartist")))


##
# MPD Monitor
##

class MpdState(Enum):

    PLAYING = 1
    PAUSED = 2
    STOPPED = 3


class MpdSong(object):

    def __init__(self, artist, album, title, date, path):
        self.artist = artist
        self.album = album
        self.title = title
        self.date = date
        self.path = path


class MpdMonitor(object):

    def __init__(self, logger, host="localhost", port=6600):
        self._logger = logger
        self._client = MPDClient()
        self._status = None
        self._currentSong = None
        self._stop = False
        self.mixerListeners = []
        self.playerListeners = []
        self._queue = SerialQueue("MPD Monitor")
        self._queue.run_async(lambda: self._client.connect(host, port))

    def __del__(self):
        self._queue.run_async(lambda: self._client.disconnect())

    def start(self):
        self._queue.run_async(self._idle)

    def stop(self):
        self._stop = True

    def _idle(self):
        if self._update_status():
            self._notify_mixer_listeners()
        if self._update_current_song():
            self._notify_player_listeners()

        idling = False
        while self._client:
            if not idling:
                self._logger.log_info("Starting MPD idle")
                self._client.send_idle()
                idling = True
            ready, _, _ = select([self._client], [], [], 1)
            if ready:
                self._logger.log_info("MPD idle loop interrupted with data available on %s" % ready)
                self._handle_events(self._client.fetch_idle())
                idling = False
            if self._stop:
                self._stop = False
                if idling:
                    self._logger.log_info("Stopping MPD idle")
                    self._client.noidle()
                break

    def _handle_events(self, events):
        self._update_status()
        for event in events:
            if event == "mixer":
                self._notify_mixer_listeners()
            if event == "player":
                self._update_current_song()
                self._notify_player_listeners()

    def _update_status(self):
        old = self._status
        self._status = self._client.status()
        return old != self._status

    def _update_current_song(self):
        old = self._currentSong
        if "songid" in self._status:
            self._currentSong = self._client.playlistid(self._status["songid"])[0]
        else:
            self._currentSong = None
        return old != self._currentSong

    def _notify_mixer_listeners(self):
        for listener in self.mixerListeners:
            listener.on_mixer_changed()

    def _notify_player_listeners(self):
        for listener in self.playerListeners:
            listener.on_player_changed()

    def get_volume(self):
        if not self._status:
            return 0
        return int(self._status["volume"])

    volume = property(get_volume)

    def get_state(self):
        if not self._status:
            return MpdState.STOPPED
        stateString = self._status["state"]
        if stateString == "play":
            return MpdState.PLAYING
        elif stateString == "pause":
            return MpdState.PAUSED
        elif stateString == "stop":
            return MpdState.STOPPED

    state = property(get_state)

    def get_current_song(self):
        if not self._currentSong:
            return None
        return MpdSong(
            artist=self._get_current_song_artist(),
            album=self._get_current_song_album(),
            title=self._get_current_song_title(),
            date=self._get_current_song_date(),
            path=self._get_current_song_path())

    def _get_current_song_artist(self):
        if self._currentSong and "artist" in self._currentSong:
            return self._currentSong["artist"]

    def _get_current_song_album(self):
        if self._currentSong and "album" in self._currentSong:
            return self._currentSong["album"]

    def _get_current_song_title(self):
        if self._currentSong and "title" in self._currentSong:
            return self._currentSong["title"]

    def _get_current_song_date(self):
        if self._currentSong and "date" in self._currentSong:
            return self._currentSong["date"]

    def _get_current_song_path(self):
        if self._currentSong and "file" in self._currentSong:
            return self._currentSong["file"]

    currentSong = property(get_current_song)

    def get_elapsed(self):
        if self._status and "elapsed" in self._status:
            return float(self._status["elapsed"])

    elapsed = property(get_elapsed)

    def get_duration(self):
        if self._status and "duration" in self._status:
            return float(self._status["duration"])

    duration = property(get_duration)


##
# Volume Monitor
##

class VolumeMonitor(object):

    def __init__(self, logger, mpdService):
        self._logger = logger
        self._mpdService = mpdService
        self._adc = ADS1115()
        self._last_value = None
        self._max_value = 32767 * 3.3 / 4.096
        self._stop = False
        self._queue = SerialQueue("Volume Monitor")

    def start(self):
        self._queue.run_async(self._iterate)

    def stop(self):
        self._stop = True

    def _iterate(self):
        while not self._stop:
            new_value = self._adc.read_adc(0, gain=1)
            if not self._last_value or abs(new_value - self._last_value) >= self._max_value / 100:
                self._last_value = new_value
                percentage = max(0, min(100, round(new_value / self._max_value * 100)))
                self._logger.log_info("Volume slider changed to %i%%" % percentage)
                self._mpdService.change_volume(percentage)
            sleep(0.2)


##
# Main
##

logger = Logger()
theme = Theme()
driver = DisplayDriver(logger)
network = NetworkService(logger)

mpdMonitor = MpdMonitor(logger)
mpdService = MpdService(logger)

volumeMonitor = VolumeMonitor(logger, mpdService)
volumeMonitor.start()

app = PlayerApp(theme, driver, logger, network, mpdMonitor, mpdService)
app.run()
