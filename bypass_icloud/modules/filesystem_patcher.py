import subprocess

class FilesystemPatcher:
    def mount_filesystems(self):
        """ Monte les partitions systèmes locales dans le ramdisk """
        subprocess.run(['mount_filesystems'], shell=True, check=True)
        print("[SUCCESS] Systèmes de fichiers montés.")

    def modify_activation_files(self):
        """ Modifie les fichiers .plist pour bypasser l'écran de verrouillage """
        subprocess.run(['mkdir', '-p', '/mnt2/wireless/Library/Preferences/'], check=True)
        subprocess.run(['cp', './com.apple.springboard.plist', '/mnt2/wireless/Library/Preferences/'], check=True)
        subprocess.run(['cp', './com.apple.preferences.plist', '/mnt2/wireless/Library/Preferences/'], check=True)
        subprocess.run(['cp', './hosts', '/etc/hosts'], check=True)
        print("[SUCCESS] Fichiers de configuration modifiés.")

    def activate_device(self):
        """ Applique les patches finaux sur le système en place """
        subprocess.run(['mv', '/Applications/Setup.app', '/Applications/Setup.app.bak'], check=True)
        subprocess.run(['cp', '-r', './Setup_patched.app', '/Applications/Setup.app'], check=True)
        subprocess.run(['chmod', '755', '/Applications/Setup.app/Setup'], check=True)
        print("[SUCCESS] Application Setup patchée et remplacée.")