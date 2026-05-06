import subprocess
import os

class RamdiskManager:
    def __init__(self, ipsw_url):
        self.ipsw_url = ipsw_url
        self.ramdisk_path = "./ramdisk/custom_ramdisk.dmg"

    def download_ipsw_firmware(self):
        """ Télécharge le firmware iPadOS pour A2152 """
        subprocess.run(['wget', '-O', 'ipsw_file.ipsw', self.ipsw_url], check=True)
        subprocess.run(['unzip', 'ipsw_file.ipsw', '-d', 'firmware_files/'], check=True)

    def create_custom_ramdisk(self):
        """ Construit un ramdisk minimal avec des outils intégrés """
        subprocess.run(['mkdir', '-p', './ramdisk_mnt'], check=True)
        subprocess.run(['dd', 'if=/dev/zero', 'of=self.ramdisk_path', 'bs=1M', 'count=200'], check=True)
        subprocess.run(['mkfs.hfsplus', '-v', 'SSHRamdisk', self.ramdisk_path], check=True)
        subprocess.run(['sudo', 'mount', '-o', 'loop', self.ramdisk_path, './ramdisk_mnt'], check=True)
        subprocess.run(['cp', '-r', './bin/*', './ramdisk_mnt/bin/'], check=True)
        subprocess.run(['sudo', 'umount', './ramdisk_mnt'], check=True)
        print("[SUCCESS] Ramdisk personnalisé créé.")

    def boot_ramdisk(self):
        """ Démarre l'iPad sur le ramdisk """
        subprocess.run(['./sshrd.sh', 'boot'], check=True)
        print("[SUCCESS] Ramdisk démarré.")