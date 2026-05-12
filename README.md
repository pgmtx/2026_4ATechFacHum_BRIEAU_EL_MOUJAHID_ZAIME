# 2026_4ATechFacHum_BRIEAU_EL_MOUJAHID_ZAIME

## Setup

### Using conda

```
conda create --name myenv python=3.13
conda activate myenv
conda install --file requirements.txt
python run main.py
``
### if you get any erreur installing the requirements run this intide 

pip install -r requirements.txt
### Using uv

```
uv sync
uv run main.py
```
