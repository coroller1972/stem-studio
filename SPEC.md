# Prompt Codex — Atelier audio macOS avec séparation Demucs

Je veux que tu implémentes une application desktop macOS appelée provisoirement **Stem Studio**.

## Objectif

L'application prend en entrée un fichier audio MP3 ou WAV, effectue automatiquement une séparation en 4 stems avec **Demucs**, puis permet d'écouter et mixer ces 4 pistes dans une seule interface.

Les 4 stems sont :

* vocals
* drums
* bass
* other

Je veux remplacer mon workflow actuel :

`fichier audio → Demucs en Python → export WAV → import dans Audacity`

par :

`fichier audio → Stem Studio → séparation → écoute/mix directement dans l'application`

## Stack imposée

Utilise :

* **Tauri 2**
* **React**
* **TypeScript**
* **Vite**
* **Web Audio API**
* **Python 3**
* **Demucs / PyTorch**
* Python lancé comme **sidecar Tauri**

Évite Electron.

Le code doit être structuré de manière à pouvoir remplacer ultérieurement le backend Python/Demucs par une implémentation CoreML ou native sans devoir réécrire toute l'UI.

## Architecture souhaitée

Structure le projet approximativement ainsi :

```text
stem-studio/
├── app/
│   ├── src/
│   │   ├── components/
│   │   ├── audio/
│   │   ├── hooks/
│   │   ├── state/
│   │   └── ...
│   ├── src-tauri/
│   └── ...
│
├── engine/
│   ├── main.py
│   ├── separator.py
│   ├── requirements.txt
│   └── ...
│
└── README.md
```

Sépare clairement :

1. moteur de séparation audio ;
2. transport audio ;
3. état de l'application ;
4. composants UI.

## Fonctionnalités MVP

### 1. Import audio

L'utilisateur doit pouvoir :

* glisser-déposer un MP3 ou WAV ;
* ou cliquer sur un bouton pour sélectionner un fichier.

Après import, afficher :

* nom du fichier ;
* durée si disponible ;
* état de traitement.

## 2. Séparation avec Demucs

Utilise le modèle Demucs :

```text
htdemucs
```

Le moteur Python reçoit le chemin du fichier et produit :

```text
vocals.wav
drums.wav
bass.wav
other.wav
```

dans un répertoire temporaire propre au projet courant.

Expose une CLI interne ressemblant à :

```bash
stem-engine separate "/path/song.mp3" --output "/path/project"
```

Le process doit communiquer avec Tauri via stdout en JSON.

Exemple de résultat final :

```json
{
  "type": "completed",
  "stems": {
    "vocals": "/tmp/project/vocals.wav",
    "drums": "/tmp/project/drums.wav",
    "bass": "/tmp/project/bass.wav",
    "other": "/tmp/project/other.wav"
  }
}
```

Prévois également des messages de progression :

```json
{
  "type": "progress",
  "progress": 0.42,
  "message": "Separating audio"
}
```

et des erreurs structurées :

```json
{
  "type": "error",
  "message": "..."
}
```

Ne parse pas des logs humains si cela peut être évité.

## 3. UI pendant la séparation

Pendant le traitement, afficher :

* une barre de progression ;
* un message d'état ;
* le nom du fichier ;
* un bouton Cancel si l'interruption propre du process est raisonnablement simple à implémenter.

Ne bloque jamais l'interface pendant Demucs.

## 4. Affichage des quatre stems

Une fois la séparation terminée, afficher quatre pistes verticalement :

```text
Vocals
[ waveform -------------------------------- ]

Drums
[ waveform -------------------------------- ]

Bass
[ waveform -------------------------------- ]

Other
[ waveform -------------------------------- ]
```

Les quatre waveforms doivent partager exactement la même timeline.

Ajoute une règle temporelle commune.

Pour le MVP, tu peux utiliser une bibliothèque telle que **WaveSurfer.js** uniquement pour la visualisation si cela simplifie fortement le développement.

Cependant :

**la lecture et la synchronisation audio doivent être gérées par notre propre moteur Web Audio API.**

Ne fais pas reposer le mixer sur quatre éléments HTML `<audio>` indépendants.

## 5. Audio engine

Crée une abstraction TypeScript dédiée, par exemple :

```text
AudioEngine
```

Responsable de :

* chargement des quatre WAV ;
* décodage ;
* play ;
* pause ;
* seek ;
* volume ;
* mute ;
* solo ;
* position courante ;
* durée ;
* synchronisation des stems.

Utilise un unique :

```text
AudioContext
```

Chaque stem doit avoir son propre :

```text
GainNode
```

Architecture :

```text
vocals AudioBufferSourceNode -> GainNode --\
drums  AudioBufferSourceNode -> GainNode ----\
bass   AudioBufferSourceNode -> GainNode ------> destination
other  AudioBufferSourceNode -> GainNode ----/
```

Les quatre sources doivent être démarrées avec exactement le même timestamp Web Audio.

Exemple conceptuel :

```ts
const startAt = audioContext.currentTime + 0.05

vocals.start(startAt, offset)
drums.start(startAt, offset)
bass.start(startAt, offset)
other.start(startAt, offset)
```

Prends correctement en compte le fait qu'un `AudioBufferSourceNode` est one-shot.

Après stop, pause ou seek, recrée les sources si nécessaire.

## 6. Contrôles par piste

Pour chaque piste :

```text
Vocals   [M] [S]  Volume ─────●────  80%
```

Implémente :

* Mute ;
* Solo ;
* volume 0–100 %.

Le volume d'une piste doit utiliser son `GainNode`.

Le Solo doit fonctionner comme sur un mixer classique :

* s'il n'y a aucun Solo, toutes les pistes non mutées sont audibles ;
* s'il existe au moins un Solo, seules les pistes en Solo et non mutées sont audibles.

## 7. Transport global

En bas ou en haut de la timeline, ajouter :

* Play ;
* Pause ;
* retour au marqueur de départ ;
* affichage temps courant / durée.

Raccourci :

```text
Space = Play / Pause
```

## 8. Marqueur de début de lecture

C'est une fonctionnalité importante.

L'utilisateur doit pouvoir cliquer ou déplacer un marqueur sur la timeline.

Exemple :

```text
00:00        00:30        01:00        01:30
 |-------------|------------|------------|
                           ▲
                      start marker
```

Appelle cette valeur :

```ts
startMarkerSeconds
```

Lorsque l'utilisateur clique sur Play alors que la lecture est arrêtée ou qu'il utilise explicitement "Play from marker", la lecture doit commencer à cette position.

Exemple :

```ts
startMarkerSeconds = 83.45
```

Les quatre stems doivent alors démarrer à exactement :

```text
83.45 secondes
```

sans désynchronisation.

Permets de déplacer facilement ce marqueur à la souris.

## 9. Seek

L'utilisateur doit aussi pouvoir cliquer dans la timeline pour déplacer la tête de lecture.

Distingue dans le modèle d'état :

```text
playheadPosition
```

et :

```text
startMarkerPosition
```

Ce sont deux concepts distincts.

## 10. Gestion de projet temporaire

Pour chaque audio importé, crée un workspace local temporaire.

Exemple :

```text
~/Library/Application Support/Stem Studio/projects/<uuid>/
```

ou un dossier temporaire approprié.

Il contient au minimum :

```text
source metadata
vocals.wav
drums.wav
bass.wav
other.wav
```

Ne modifie jamais le fichier source original.

## UX

Je veux une interface sobre de type outil audio professionnel.

Évite un design SaaS avec grosses cartes marketing.

Inspiration générale :

* DAW minimaliste ;
* Ableton / Logic pour la densité fonctionnelle ;
* interface très épurée.

Layout principal :

```text
┌──────────────────────────────────────────────┐
│ Stem Studio                  song.mp3        │
├──────────────────────────────────────────────┤
│             timeline commune                 │
│                                              │
│ Vocals [M][S] [volume] | waveform           │
│ Drums  [M][S] [volume] | waveform           │
│ Bass   [M][S] [volume] | waveform           │
│ Other  [M][S] [volume] | waveform           │
│                                              │
├──────────────────────────────────────────────┤
│  ▶  ❚❚    01:23.450 / 04:18.220             │
│                  start marker: 01:20.000     │
└──────────────────────────────────────────────┘
```

Prévois correctement :

* dark mode ;
* petits écrans de laptop ;
* redimensionnement de fenêtre ;
* feedback hover ;
* raccourcis clavier.

## Gestion d'état

Utilise une gestion d'état simple et explicite.

Évite une architecture Redux lourde si elle n'est pas nécessaire.

Par exemple Zustand convient.

Le state devrait contenir approximativement :

```ts
type StemName = "vocals" | "drums" | "bass" | "other"

interface StemState {
  volume: number
  muted: boolean
  solo: boolean
}

interface ProjectState {
  sourcePath: string | null
  stems: Record<StemName, string> | null

  status:
    | "empty"
    | "separating"
    | "ready"
    | "error"

  progress: number

  currentTime: number
  duration: number

  startMarkerSeconds: number

  tracks: Record<StemName, StemState>
}
```

Adapte ce modèle si tu identifies une meilleure architecture.

## Sécurité Tauri

Respecte le système de permissions/capabilities Tauri 2.

Ne donne pas au frontend des permissions filesystem ou shell plus larges que nécessaire.

Le lancement du sidecar Python doit être explicitement autorisé.

## Packaging Python

Je veux que l'utilisateur final n'ait pas à installer :

* Python ;
* pip ;
* Demucs ;
* PyTorch.

Prépare l'architecture pour packager le moteur Python en exécutable autonome, par exemple avec PyInstaller.

Documente précisément la procédure.

Si PyInstaller + PyTorch/Demucs impose des contraintes particulières sur macOS, documente-les plutôt que de contourner le problème avec une solution fragile.

Le développement peut dans un premier temps appeler directement le Python du virtualenv.

Mais le code doit distinguer :

```text
development engine
```

et :

```text
packaged sidecar
```

proprement.

## Apple Silicon

L'application cible prioritairement :

```text
macOS Apple Silicon
```

Si possible, utilise automatiquement l'accélération PyTorch MPS.

Le moteur Python doit choisir approximativement :

```python
if torch.backends.mps.is_available():
    device = "mps"
else:
    device = "cpu"
```

Mais vérifie la compatibilité réelle avec Demucs et prévois un fallback CPU propre en cas d'erreur MPS.

L'application ne doit pas planter si MPS échoue.

## Logs et erreurs

Prévois des erreurs utilisateur compréhensibles :

```text
Unable to decode this audio file.
Stem separation failed.
Not enough disk space.
Demucs process terminated unexpectedly.
```

Les détails techniques peuvent être envoyés dans les logs.

Ne montre pas une stack trace Python brute à l'utilisateur.

## Hors scope pour le MVP

Ne développe pas pour l'instant :

* édition/cut audio ;
* export du mix ;
* effets audio ;
* EQ ;
* pitch shifting ;
* time stretching ;
* changement de BPM ;
* enregistrement ;
* plugins VST/AU ;
* comptes utilisateur ;
* cloud ;
* synchronisation ;
* backend web ;
* base de données distante.

Je veux avant tout que le cœur suivant soit extrêmement robuste :

```text
Import
→ Separate
→ Display
→ Play synchronized stems
→ Mute / Solo / Volume
→ Seek
→ Start marker
```

## Qualité attendue

Ne produis pas simplement un prototype jetable.

Je veux :

* TypeScript strict ;
* composants petits et cohérents ;
* logique audio hors des composants React ;
* erreurs correctement traitées ;
* pas de duplication inutile ;
* interfaces/types explicites ;
* commentaires seulement là où ils apportent réellement quelque chose ;
* code lisible ;
* architecture permettant l'évolution.

## Tests

Ajoute au minimum des tests sur la logique indépendante de l'audio natif :

* calcul du gain avec mute/solo ;
* changement de position ;
* start marker ;
* transitions play/pause/seek ;
* parsing des événements JSON du sidecar.

Pour les parties difficilement testables automatiquement, donne une checklist de test manuel.

## README

Écris un README complet expliquant :

1. prérequis ;
2. installation ;
3. création du virtualenv Python ;
4. installation de Demucs/PyTorch ;
5. lancement en développement ;
6. architecture du projet ;
7. packaging du sidecar ;
8. build de l'app macOS ;
9. problèmes connus ;
10. fallback MPS → CPU.

## Méthode de travail

Commence par examiner l'état actuel du repository.

Ensuite :

1. propose brièvement l'architecture et les principaux choix techniques ;
2. initialise ou adapte le projet ;
3. implémente le backend Python ;
4. implémente le bridge Tauri ;
5. implémente `AudioEngine` ;
6. implémente l'état applicatif ;
7. implémente l'UI ;
8. ajoute les tests ;
9. lance les tests/typecheck/build ;
10. corrige les erreurs jusqu'à obtenir un état fonctionnel.

Ne t'arrête pas après avoir créé un squelette.

Implémente réellement le flux MVP de bout en bout.

Lorsque tu rencontres une ambiguïté mineure, prends une décision raisonnable et documente-la plutôt que de bloquer.

À la fin, donne-moi :

* un résumé de ce qui est implémenté ;
* les principaux fichiers créés/modifiés ;
* les commandes pour lancer l'application ;
* ce qui reste éventuellement incomplet ;
* les risques techniques identifiés autour de Demucs/PyTorch/Tauri packaging.
