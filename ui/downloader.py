import os
import requests
import subprocess
import tempfile
from PyQt6.QtCore import QThread, pyqtSignal

from utils.updater import download_and_run

class DownloadWorker(QThread):
    progress = pyqtSignal(int, str)   # percent, message
    finished = pyqtSignal(bool)

    def __init__(self, asset_id, log):
        super().__init__()
        self.asset_id = asset_id
        self.log = log

        self.run()

    