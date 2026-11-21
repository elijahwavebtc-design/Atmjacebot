# Guide : mettre le bot en ligne 24h/24

## 1. Créer le bot sur Telegram
1. Ouvre @BotFather, envoie `/newbot`, choisis un nom et un identifiant (terminé par `bot`).
2. BotFather te donne un **token**. Garde-le secret : il ne doit jamais être écrit dans le code ni envoyé dans un chat.

## 2. Récupérer ton identifiant Telegram (pour être le seul admin)
Écris à @userinfobot : il te répond avec ton **Id** (un nombre). C'est ta valeur `ADMIN_IDS`.

## 3. Tester sur ton PC (facultatif)
```powershell
cd C:\Users\MESMIN\Desktop\MonBot
pip install -r requirements.txt
$env:BOT_TOKEN="ton_token"
$env:ADMIN_IDS="ton_id"
python bot.py
```
Arrête le test (Ctrl+C) avant de déployer : deux copies du bot avec le même token se bloquent.

## 4. Mettre le code sur GitHub
1. Crée un dépôt **privé** sur github.com.
2. Dans le dossier du bot :
```powershell
git init
git add .
git commit -m "bot"
git branch -M main
git remote add origin https://github.com/TON_COMPTE/TON_DEPOT.git
git push -u origin main
```
Le fichier `.gitignore` empêche d'envoyer les secrets et la base de données.

## 5. Déployer sur Railway
1. railway.app, puis New Project, puis Deploy from GitHub repo, et choisis ton dépôt.
2. Onglet **Variables** : ajoute
   - `BOT_TOKEN` = ton token
   - `ADMIN_IDS` = ton identifiant
   - `DB_PATH` = `/data/bot.db`
3. Ajoute un **Volume** monté sur `/data` (sinon la liste des inscrits est effacée à chaque redéploiement).
4. Vérifie que le service a **une seule instance** et que la commande de démarrage est `python bot.py`.
5. Regarde les logs : tu dois voir « Bot démarré ».

## 6. Utilisation (dans ton chat avec le bot)
- `/aide` : liste des commandes
- `/stats` : nombre d'inscrits et de membres par groupe
- `/diviser` : répartition aléatoire en groupe A et groupe B
- `/envoyer A` (ou `B`, `TOUS`, `AFFILIES`), puis tu envoies ton message (texte, ou image avec légende), puis tu confirmes
- `/supprimer A` (ou `B`) : supprime les membres du groupe
- `/code_ajouter CODE`, `/code_supprimer CODE`, `/codes` : gérer les codes d'affiliation
- Lien d'affiliation automatique : `https://t.me/TON_BOT?start=CODE`

Les inscrits ne voient aucune de ces commandes : le bot ignore tous ceux qui ne sont pas dans `ADMIN_IDS`.

## Bon à savoir
- Telegram limite l'envoi à environ 30 messages par seconde : le bot envoie environ 20 par seconde, donc 10 000 messages prennent environ 8 minutes. Tu reçois un point d'avancement tous les 1000 envois.
- Le bot ne peut écrire qu'à ceux qui l'ont démarré. Ceux qui bloquent le bot sont marqués et ignorés ensuite.
- Pour passer un code d'affiliation : l'inscrit peut le saisir après son inscription (bouton « J'ai un code d'affiliation ») ou arriver via ton lien d'affiliation.
- Si un token a été partagé par erreur : `/revoke` dans @BotFather pour en générer un nouveau.
