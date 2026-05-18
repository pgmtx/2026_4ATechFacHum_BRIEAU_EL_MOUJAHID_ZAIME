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

# ChunkyMemo — Document de conception : traitement du signal
 
---
 
## Signaux acquis
 
| Signal | Ce que le BITalino envoie | Unité |
|--------|--------------------------|-------|
| PPG | Variation de volume sanguin dans le doigt | valeur brute 0–1023 (10 bits) |
| PZT | Déformation de la ceinture thoracique | valeur brute 0–1023 (10 bits) |
 
| Entrée | Ce que le jeu capture | Unité |
|--------|-----------------------|-------|
| Clavier (touches directionnelles) | Horodatage de chaque appui | timestamp (ms) |
 
---
 
## PPG → Fréquence cardiaque (FC)
 
**Ce qu'on extrait :** nombre de battements par minute
 
**Pourquoi :** la FC augmente sous charge cognitive. La littérature montre une hausse de 3–8 bpm entre charge faible et charge élevée sur des tâches de mémoire de travail.
> Causse et al. (2023) "Task-evoked pulse wave amplitude tracks cognitive load" — Scientific Reports
> https://www.nature.com/articles/s41598-023-48917-5
 
**Transformations requises :**
1. Filtre passe-bande Butterworth ordre 4, bande [0.7–4.0 Hz] → élimine dérive lente + bruit haute fréquence
2. Détection de pics → chaque pic = un battement
3. FC = 60 / intervalle moyen entre les 5 derniers pics (en secondes)
**Justification scientifique des paramètres :**
> Elgendi (2012) "On the Analysis of Fingertip Photoplethysmogram Signals" — Current Cardiology Reviews
> https://www.ingentaconnect.com/content/ben/ccr/2012/00000008/00000001
> Définit le pipeline standard PPG → FC, filtre [0.5–4 Hz], détection de pics. Référence de base du domaine.
 
> Charlton et al. (2022) "Assessing Cardiovascular Function using an Arterial Blood Pressure Waveform" — Physiological Measurement
> https://iopscience.iop.org/article/10.1088/0967-3334/31/1/R01/meta
> Valide les seuils de fréquence pour le filtrage PPG.
 
---
 
## PPG → Amplitude de l'onde de pouls (PWA)
 
**Ce qu'on extrait :** hauteur de chaque battement dans le signal PPG, normalisée par rapport à la baseline
 
**Pourquoi :** sous charge cognitive, le système nerveux sympathique provoque une vasoconstriction périphérique — le sang arrive moins fort au bout du doigt, donc le pic PPG est plus petit. La PWA diminue quand la charge augmente, indépendamment de la FC. Ces deux métriques sont extraites du même signal PPG, sans capteur supplémentaire.
> Causse et al. (2023) "Task-evoked pulse wave amplitude tracks cognitive load" — Scientific Reports
> https://www.nature.com/articles/s41598-023-48917-5
 
**Transformations requises :**
1. Même filtre que FC : Butterworth [0.7–4.0 Hz]
2. Pour chaque battement détecté : PWA_brute = valeur_pic − valeur_creux précédent
3. PWA_normalisée = PWA_brute / PWA_baseline (calculée lors des 30 s de repos initial)
**Justification scientifique des paramètres :**
> Causse et al. (2023) — même référence ci-dessus
> Montre une diminution significative de la PWA corrélée à la charge cognitive sur des tâches de mémoire de travail, avec un effet observable dès les premières secondes de la tâche.
 
---
 
## PZT → Rythme respiratoire (RR)
 
**Ce qu'on extrait :** nombre de cycles respiratoires par minute
 
**Pourquoi :** les épisodes mentalement exigeants s'accompagnent d'une respiration plus rapide. Le PZT répond quasi-immédiatement (contrairement à l'EDA qui a une latence de 3–5 s), ce qui le rend adapté aux fenêtres temporelles courtes de ChunkyMemo.
> Grassmann et al. (2016) "Respiratory Changes in Response to Cognitive Load: A Systematic Review" — Neural Plasticity
> https://doi.org/10.1155/2016/8146809
 
**Transformations requises :**
1. Filtre passe-bande Butterworth ordre 4, bande [0.1–0.8 Hz] → garde uniquement les fréquences respiratoires (6–48 cycles/min)
2. Détection de pics → chaque pic = une inspiration
3. RR = 60 / intervalle moyen entre les 3 derniers pics (en secondes)
**Justification scientifique des paramètres :**
> Charlton et al. (2018) "Breathing Rate Estimation from the Electrocardiogram and Photoplethysmogram: A Review" — IEEE Reviews in Biomedical Engineering
> https://ieeexplore.ieee.org/abstract/document/8081839
> Valide le filtre [0.1–0.8 Hz] comme standard pour l'extraction non-invasive du rythme respiratoire.
 
---
 
## PZT → Détection d'apnée cognitive
 
**Ce qu'on extrait :** absence prolongée de cycle respiratoire (pause involontaire liée à la concentration)
 
**Pourquoi :** sous charge cognitive intense, le joueur peut retenir brièvement sa respiration sans s'en rendre compte. Ces micro-apnées sont un marqueur de concentration extrême distinct de l'accélération respiratoire.
> Grassmann et al. (2016) — même référence que RR
 
**Transformations requises :**
1. Même filtre que RR : Butterworth [0.1–0.8 Hz]
2. Apnée détectée si aucun pic respiratoire pendant > 4 secondes
3. Le seuil de 4 s est choisi pour capturer les pauses de concentration sans déclencher de faux positifs lors des transitions normales entre inspirations (intervalle normal max ≈ 10 s à 6 cycles/min)
---
 
## Clavier → Temps de réaction (RT)
 
**Ce qu'on extrait :** délai entre l'affichage d'une flèche et l'appui de la touche correspondante
 
**Pourquoi :** le temps de réaction est l'un des indicateurs comportementaux les plus robustes de la charge cognitive. Plus la charge augmente, plus le RT s'allonge. C'est une mesure complémentaire aux signaux physiologiques : là où PPG et PZT mesurent l'état interne du joueur, le RT mesure la performance observable.
> Welford (1980) "Reaction Times" — Academic Press
> Référence fondatrice établissant la relation entre charge cognitive et allongement du temps de réaction.
 
> Hick (1952) "On the rate of gain of information" — Quarterly Journal of Experimental Psychology
> Montre que le RT augmente avec la complexité de la décision à prendre (Hick's Law).
 
**Transformations requises :**
1. À chaque affichage de flèche : enregistrement du timestamp t_affichage
2. À chaque appui touche : enregistrement du timestamp t_reponse
3. RT = t_reponse − t_affichage (en ms)
4. RT_moyen = moyenne glissante sur les 3 dernières réponses
5. Taux d'erreur = nombre de mauvaises touches / nombre total de réponses (par niveau)
---
 
## Combinaison → Indice de charge cognitive composite (I_cog)
 
**Ce qu'on calcule :** un score unique résumant l'état de charge cognitive du joueur à chaque instant, combinant 4 métriques issues de 3 sources indépendantes (cardiovasculaire, respiratoire, comportementale).
 
**Pourquoi une baseline individuelle :** les valeurs physiologiques de repos varient fortement d'une personne à l'autre (FC de repos entre 50 et 90 bpm selon les individus). Utiliser des seuils fixes serait non fiable. On normalise donc chaque métrique par rapport aux valeurs propres du joueur mesurées au repos.
 
**Procédure de calibration (30 secondes au lancement) :**
- Le joueur est au repos, immobile, yeux ouverts
- On calcule μ (moyenne) et σ (écart-type) pour FC, PWA et RR
- Pour le RT : μ et σ calculés sur les 5 premières réponses du niveau 1 (séquences courtes = faible charge)
- Ces valeurs servent de référence pour toute la session
**Calcul de l'indice :**
 
Pour chaque métrique à chaque instant t :
```
z_FC  = (FC_t  − μ_FC)  / σ_FC         # monte sous charge → signe +
z_PWA = (PWA_t − μ_PWA) / σ_PWA × −1   # descend sous charge → signe inversé
z_RR  = (RR_t  − μ_RR)  / σ_RR         # monte sous charge → signe +
z_RT  = (RT_t  − μ_RT)  / σ_RT         # monte sous charge → signe +
```
 
Indice composite :
```
I_cog = (z_FC + z_PWA + z_RR + z_RT) / 4
```
 
**Seuil de surcharge :** I_cog > 1.5 → retour visuel dans le dashboard
 
**Justification de l'approche z-score :**
Le z-score est la méthode standard en psychophysiologie pour comparer des mesures inter-individuelles. Un z-score de 1.5 correspond à une déviation de 1.5 écart-type par rapport au repos individuel, conservateur (évite les faux positifs) tout en restant sensible aux variations réelles.
 
---
 
## Récapitulatif
 
| Source | Métrique | Traitement | Lien charge cognitive |
|--------|----------|------------|-----------------------|
| PPG | FC (bpm) | Butterworth [0.7–4.0 Hz] + détection pics | FC ↑ 3–8 bpm sous charge [Causse 2023] |
| PPG | PWA normalisée | Butterworth [0.7–4.0 Hz] + amplitude pic-creux | PWA ↓ vasoconstriction sympathique [Causse 2023] |
| PZT | RR (cycles/min) | Butterworth [0.1–0.8 Hz] + détection pics | RR ↑ sous charge [Grassmann 2016] |
| PZT | Apnée (booléen) | Butterworth [0.1–0.8 Hz] + seuil 4 s | Pause > 4s = concentration intense [Grassmann 2016] |
| Clavier | RT (ms) | Différence de timestamps | RT ↑ sous charge cognitive [Welford 1980] |
| Clavier | Taux d'erreur (%) | Comptage par niveau | Erreurs ↑ sous surcharge [Hick 1952] |