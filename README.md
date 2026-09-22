# Poké Deals

Bot personnel qui vérifie périodiquement les nouvelles annonces Pokémon sur
Vinted et Leboncoin, écarte les langues étrangères explicitement indiquées et
compare les annonces identifiables au guide de prix public Cardmarket.

## Comportement

- recherche `carte pokemon` toutes les 15 minutes ;
- aucune limite de prix ;
- alerte à partir de 25 % sous la cote estimée ;
- rejette les annonces indiquant japonais, anglais, allemand, italien, etc. ;
- rejette les mots suspects tels que `proxy`, `fake` et `reproduction` ;
- mémorise les annonces déjà analysées pour éviter les doublons ;
- n’achète jamais automatiquement.

Une estimation automatisée n’est pas une garantie. Toujours contrôler les
photos, le numéro de carte, l’état, la langue et l’authenticité avant achat.

## Activation

1. Dans le dépôt GitHub, ouvrir **Settings**.
2. Ouvrir **Secrets and variables** puis **Actions**.
3. Créer un secret nommé exactement `DISCORD_WEBHOOK_URL`.
4. Coller comme valeur l’URL du webhook Discord.
5. Ouvrir **Actions**, choisir **Recherche bonnes affaires Pokemon**, puis
   **Run workflow**.

Le premier passage mémorise les annonces déjà présentes et publie seulement un
message d’activation. Les passages suivants ne préviennent que pour les nouvelles
annonces correspondant suffisamment à une référence Cardmarket.

## Limites

Vinted et Leboncoin peuvent modifier leurs pages ou limiter les accès automatisés.
Dans ce cas, une source peut temporairement renvoyer zéro résultat sans que
l’autre cesse de fonctionner. Les annonces dont le titre ne permet pas d’identifier
une carte précise ne sont pas présentées comme de bonnes affaires certaines.
