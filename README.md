# ChunkyMemo

Jeu interactif de mémoire de travail basé sur la loi de Miller (7±2).  
Le joueur reproduit des séquences de flèches de plus en plus longues, pendant que le système mesure sa charge cognitive en temps réel via des capteurs physiologiques BITalino.

---

## Matériel requis

- Carte **BITalino (r)evolution Plugged Kit BLE/BT**
- Capteur **PPG** (clip digital, index)
- Capteur **PZT** (ceinture thoracique)
- Bluetooth activé sur le PC

> Si le BITalino n'est pas disponible, le jeu tourne quand même mais sans données physiologiques.

---

## Installation

Choisissez une des méthodes suivantes :

### Avec conda

```bash
conda create --name myenv python=3.13
conda activate myenv
pip install -r requirements.txt
```

### Avec uv

```bash
uv sync
```

### Avec Python et pip

```bash
pip install -r requirements.txt
```

---

## Lancement

Choisissez une des méthodes suivantes :

### Avec conda

```bash
conda activate myenv
python main.py
```

### Avec uv

```bash
uv run main.py
```

### Avec Python et pip

```bash
python main.py
```

---

## Ce que fait le programme

`main.py` lance deux fenêtres en parallèle :

| Fenêtre | Description |
|---------|-------------|
| **Jeu** | Séquences de flèches à reproduire au clavier |
| **Graphes** | Signaux PPG + PZT + fréquence cardiaque + I_cog en temps réel |

À la fin de la session, les résultats sont sauvegardés dans le dossier `sessions/`.

---

## Contrôles

| Touche | Action |
|--------|--------|
| `↑` `↓` `←` `→` | Reproduire la séquence |
| `Échap` | Quitter / retour menu |

---

## Structure du projet

```
2026_4ATechFacHum_BRIEAU_EL_MOUJAHID_ZAIME/
├── main.py                  ← point d'entrée
├── game.py                  ← logique du jeu
├── game_runner.py           ← processus jeu + événements
├── biosignal_monitor.py     ← acquisition BITalino + graphes
├── analysis.py              ← figures comparatives Normal vs Chunking
├── config.py                ← configuration (MAC, ports, filtres)
├── requirements.txt
├── README.md
└── sessions/                ← données et graphiques sauvegardés
```

---

## Dépendances principales

| Package | Rôle |
|---------|------|
| `pygame` | Interface graphique du jeu |
| `scipy` | Filtres Butterworth + détection de pics |
| `numpy` | Calcul sur les buffers de signal |
| `matplotlib` | Graphiques temps réel |
| `plux` | Communication avec le BITalino (inclus dans le repo) |
