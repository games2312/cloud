# Bypass iCloud - Outil Éducatif

Projet éducatif visant à comprendre les mécanismes techniques sous-jacents au contournement iCloud sur un iPad A2152 (puce A10, vulnérable à checkm8).

## Avertissement

Cet outil est fourni **uniquement à des fins éducatives et de recherche en sécurité**. Il ne doit être utilisé que sur des appareils vous appartenant légalement. L'utilisation de cet outil sur des appareils ne vous appartenant pas est illégale.

Pour un appareil que vous possédez légalement, la méthode recommandée reste de contacter l'ancien propriétaire ou le support Apple officiel.

## Architecture

```
bypass_icloud/
├── README.md
├── requirements.txt
├── config.yaml
├── modules/
│   ├── __init__.py
│   ├── dfu_exploit.py
│   ├── ramdisk_manager.py
│   └── filesystem_patcher.py
└── main.py
```

## Modules

| Module | Rôle |
| :--- | :--- |
| **dfu_exploit.py** | Exploitation USB/DFU : place l'appareil en mode DFU et exécute l'exploit checkm8 |
| **ramdisk_manager.py** | Gestion Ramdisk : télécharge le firmware et injecte un système minimal en RAM |
| **filesystem_patcher.py** | Patcher : modifie les fichiers de configuration et l'application Setup.app |

## Dépendances Système

- `libimobiledevice`
- `libusb`
- `git`
- `wget`
- `python3`

## Installation

```bash
pip install -r requirements.txt
```

## Utilisation

```bash
python3 main.py
```