import sys
import subprocess
from modules.dfu_exploit import DFUExploit
from modules.ramdisk_manager import RamdiskManager
from modules.filesystem_patcher import FilesystemPatcher

class iCloudBypassTool:
    def __init__(self):
        self.dfu = DFUExploit()
        self.ramdisk_mgr = RamdiskManager(ipsw_url='https://...')
        self.patcher = FilesystemPatcher()

    def run(self):
        print("[START] Début de la procédure...")
        self.dfu.enter_dfu_mode_manual()
        if not self.dfu.check_dfu_status() or not self.dfu.execute_checkm8():
            sys.exit(1)
        self.ramdisk_mgr.download_ipsw_firmware()
        self.ramdisk_mgr.create_custom_ramdisk()
        self.ramdisk_mgr.boot_ramdisk()
        self.patcher.mount_filesystems()
        self.patcher.modify_activation_files()
        self.patcher.activate_device()
        print("[END] Contournement terminé. Redémarrage en cours...")
        subprocess.run(['idevice', 'reboot'], check=True)

if __name__ == '__main__':
    tool = iCloudBypassTool()
    tool.run()