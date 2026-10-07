# Submitting a Petite Cup du Jour

Played a PCDJ that isn't on the rankings yet? You can add it from your own game log at
https://aizpunr.github.io/PCDJ-Rankings/submit.html

## 1. Get your log

The cup tracker writes every round to

```
C:\Program Files (x86)\Steam\steamapps\common\Zeepkist\BepInEx\LogOutput.log
```

Zeepkist overwrites this file each time it starts, so copy it **before** you launch the game again.

If you left before the final, your log stops early. Send it anyway: when several people send a log for the same cup, the most complete one is used.

## 2. Drop it and check

Drop the file on the page. It is read in your browser first and nothing is uploaded until you press Submit. Then fill in:

- **PCDJ number**: the # in the map names, for example 52 for "PCDJ #52 - Bankbanknewnew". It is filled in with the next number after the last cup on the site.
- **Date**: defaults to the most recent Wednesday.
- **Map 1 and map 2**: the names as shown in game.
- **Mappers**: pick them from the list if they were in the lobby, or type their names. Leave a mapper empty if you don't know. A mapper who was in the lobby is not counted as a player.
- **Also exclude**: only people who were in the lobby but did not race, such as a caster. Leave everyone else in.

The preview shows the winner, the podium and the full leaderboard. If it says there is no single winner, the log does not contain the whole cup.

Regular cups only. Troll and Roulette cups are added by hand.

## 3. Send it

Complete the anti-bot check and press Submit. The table at the bottom shows what happens next:

| Status | Meaning |
|---|---|
| received | Waiting for aizpun's PC to pick it up (about every 15 minutes while it is on). |
| processed | Rankings computed. Waiting for aizpun to check and publish. |
| published | Live on the rankings. |
| duplicate | That cup was already processed, or this exact file was already sent. |
| superseded | Someone sent a more complete log for the same cup. |
| failed | The pipeline stopped. The note says why; ping aizpun. |

A cup can fail on purpose: if the PCDJ number does not follow the last cup on the site, or the date is not one week after it, a cup in between is probably missing (for example a Troll cup), and aizpun adds it by hand.

## Privacy

The service stores your log, the details you typed and the name you gave (if any). It does not store your IP address.
