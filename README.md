# Transcripteur et commentaires YouTube avec Streamlit

Ce projet propose une petite application web réalisée avec **Streamlit** pour
récupérer la transcription (sous‑titres) et les commentaires associés à une
vidéo YouTube.  L'outil s'appuie sur le programme ligne de commande
[`yt-dlp`](https://github.com/yt-dlp/yt-dlp) pour extraire les données.

## Prérequis

1. **Python 3.8 ou supérieur** doit être installé sur votre machine.
2. **yt‑dlp** doit être installé et accessible via la ligne de commande.  Vous
   pouvez suivre les instructions officielles pour l'installer :
   https://github.com/yt-dlp/yt-dlp
3. Les dépendances Python nécessaires sont listées dans
   `requirements.txt`.  Installez‑les avec :

   ```bash
   pip install -r requirements.txt
   ```

   Cela installera notamment `streamlit` et `pysrt` pour le parsing des sous‑titres.

## Lancer l'application

Une fois les dépendances installées, lancez l'application en exécutant :

```bash
streamlit run app.py
```

Streamlit démarre alors un serveur local et affiche une URL dans la console.
Ouvrez cette URL dans votre navigateur pour accéder à l'interface.  Entrez
l'adresse de votre vidéo YouTube et choisissez la langue des sous‑titres.  Le
programme téléchargera les sous‑titres (ou générera des sous‑titres
automatiques si nécessaire) ainsi que les commentaires et les affichera à
l'écran.  Vous pourrez ensuite les télécharger au format texte.

## Remarques

- La récupération des commentaires peut être longue pour les vidéos très
  populaires.  Un indicateur de progression s'affiche pendant le traitement.
- Seules les langues pour lesquelles des sous‑titres existent pourront
  produire une transcription.  En l'absence de sous‑titres manuels ou
  automatiques dans la langue choisie, l'application tentera de récupérer
  ceux disponibles (par exemple l'anglais) si possible.
- Ce projet ne fait pas appel à l'API officielle de YouTube et ne nécessite
  pas de clé API.
