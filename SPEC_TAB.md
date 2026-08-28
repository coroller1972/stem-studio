# Prompt Codex — Ajouter la transcription basse et batterie à Stem Studio

Je veux étendre mon application desktop **Stem Studio**, déjà fonctionnelle.

L’application est actuellement basée sur :

* Tauri 2
* React
* TypeScript
* Vite
* Web Audio API
* backend Python packagé comme sidecar
* séparation de stems audio déjà fonctionnelle

Le pipeline actuel produit notamment :

```text
vocals.wav
drums.wav
bass.wav
other.wav
```

Je veux maintenant ajouter une fonctionnalité de **transcription musicale** à partir des stems isolés, dans un premier temps pour :

* basse
* batterie

L’objectif final est de pouvoir obtenir :

* MIDI
* MusicXML
* tablature basse
* partition batterie

Je ne veux pas écrire directement du Guitar Pro `.gp` dans ce MVP. MusicXML et MIDI doivent être les formats d’échange principaux.

---

## Objectif fonctionnel

Ajouter le pipeline suivant :

```text
audio original
   ↓
stem separation
   ↓
bass.wav / drums.wav
   ↓
transcription
   ↓
événements musicaux structurés
   ↓
beat tracking / quantification
   ↓
MIDI / MusicXML
   ↓
partition / tablature affichée dans l'app
```

L’architecture doit être suffisamment modulaire pour pouvoir remplacer ultérieurement les modèles de transcription.

---

# 1. Principe architectural important

Ne construis PAS toute l’application autour de MIDI ou MusicXML.

Je veux une représentation musicale interne indépendante des formats d’export.

Par exemple :

```ts
export interface NoteEvent {
  id: string

  detectedStartSeconds: number
  detectedEndSeconds: number

  quantizedStartBeat?: number
  quantizedDurationBeats?: number

  midiPitch: number
  velocity: number

  confidence?: number
}

export type DrumInstrument =
  | "kick"
  | "snare"
  | "closed_hihat"
  | "open_hihat"
  | "ride"
  | "crash"
  | "high_tom"
  | "mid_tom"
  | "low_tom"
  | "other"

export interface DrumEvent {
  id: string

  detectedTimeSeconds: number
  quantizedBeat?: number

  instrument: DrumInstrument
  velocity: number
  confidence?: number
}
```

Adapte ces structures si nécessaire.

Important :

* toujours conserver le timing brut détecté par le modèle ;
* ne jamais écraser ces valeurs lors de la quantification ;
* stocker séparément la position musicale quantifiée.

---

# 2. Architecture backend Python

Créer une abstraction dédiée à la transcription.

Par exemple :

```python
class BassTranscriber:
    def transcribe(self, audio_path: str) -> BassTranscription:
        ...

class DrumTranscriber:
    def transcribe(self, audio_path: str) -> DrumTranscription:
        ...
```

Le backend Python ne doit pas exposer directement les structures spécifiques des bibliothèques utilisées.

Normalise immédiatement les résultats dans nos propres modèles.

---

# 3. Transcription basse

Utiliser en priorité :

**Spotify Basic Pitch**

Le stem `bass.wav` est déjà isolé, ce qui devrait améliorer sensiblement la qualité de transcription.

Le pipeline souhaité est :

```text
bass.wav
   ↓
Basic Pitch
   ↓
pitch / onset / offset / velocity
   ↓
NoteEvent[]
```

Je veux récupérer au minimum :

* pitch MIDI ;
* début de note ;
* fin de note ;
* vélocité ;
* confiance si disponible.

Ne fais pas de la sortie MIDI générée par Basic Pitch la source de vérité.

La source de vérité doit être notre `NoteEvent[]`.

Le MIDI sera ensuite généré à partir de ces événements.

---

# 4. Transcription batterie

Pour la batterie, ne pas utiliser Basic Pitch.

Utiliser en priorité un modèle de transcription de batterie basé sur :

**ADTOF / ADTOF PyTorch**

Le stem `drums.wav` est déjà disponible.

Le pipeline souhaité :

```text
drums.wav
   ↓
ADTOF
   ↓
onsets + drum classes
   ↓
DrumEvent[]
```

Les classes doivent être normalisées au minimum vers :

```text
kick
snare
closed_hihat
open_hihat
ride
crash
high_tom
mid_tom
low_tom
other
```

Si le modèle produit des classes plus détaillées, implémente une table de mapping.

Ne fais pas dépendre le frontend directement des classes internes d’ADTOF.

---

# 5. General MIDI drums

Prévoir un mapping General MIDI pour les exports MIDI.

Valeurs de référence :

```text
Kick          -> 36
Snare         -> 38
Closed Hi-Hat -> 42
Open Hi-Hat   -> 46
Crash         -> 49
Ride          -> 51
```

Pour les toms, utiliser les notes General MIDI appropriées.

Centralise ce mapping dans un module dédié.

Ne disperse pas les numéros MIDI dans plusieurs fichiers.

---

# 6. Beat tracking

Une transcription en secondes ne suffit pas pour produire une partition propre.

Ajouter une étape séparée :

```text
audio
   ↓
beat tracking
   ↓
tempo + beat positions
```

Je veux une abstraction du type :

```ts
interface TempoMap {
  bpm: number

  beats: Array<{
    beatIndex: number
    timeSeconds: number
  }>

  timeSignature?: {
    numerator: number
    denominator: number
  }
}
```

Pour le MVP, un tempo global unique est acceptable si la détection est fiable.

Mais structure le code de manière à pouvoir supporter plus tard :

* variations de tempo ;
* plusieurs signatures rythmiques ;
* changements de mesure.

Tu peux utiliser une bibliothèque Python fiable pour le beat tracking, par exemple librosa ou une alternative plus adaptée si tu en identifies une.

---

# 7. Quantification

Ajouter une couche explicite de quantification.

Pipeline :

```text
detected timestamp
   ↓
tempo map
   ↓
beat position
   ↓
quantized beat
```

Le système doit pouvoir quantifier au minimum :

* noire ;
* croche ;
* double croche.

Prévoir éventuellement les triolets dans l’architecture, mais ils ne sont pas obligatoires dans le MVP.

Créer une API claire, par exemple :

```ts
quantizeTime(
  timeSeconds,
  tempoMap,
  subdivision
)
```

ou l’équivalent côté Python.

Important :

conserver :

```ts
detectedStartSeconds
```

et écrire séparément :

```ts
quantizedStartBeat
```

---

# 8. Tablature basse

Une note MIDI ne détermine pas automatiquement une corde et une case.

Je veux donc une étape séparée :

```text
NoteEvent[]
   ↓
Fretboard solver
   ↓
TabNote[]
```

Créer un modèle similaire à :

```ts
interface TabNote {
  noteEventId: string

  stringIndex: number
  fret: number

  startBeat: number
  durationBeats: number
}
```

Pour le MVP, supporter une basse 4 cordes standard :

```text
E1 A1 D2 G2
```

MIDI :

```text
E1 = 28
A1 = 33
D2 = 38
G2 = 43
```

Mais l’accordage doit être configurable.

Exemples futurs possibles :

```text
D A D G
B E A D G
```

---

# 9. Fretboard solver

Ne choisis PAS simplement la première corde possible.

Pour chaque note, calcule toutes les positions physiques possibles :

```python
fret = midi_pitch - open_string_pitch
```

avec :

```text
0 <= fret <= max_fret
```

Puis choisis globalement le chemin le plus jouable.

Utilise de préférence de la programmation dynamique.

Le coût peut inclure :

```text
fret movement
string movement
large hand shift
large stretch
very high fret penalty
optional open-string preference
```

Par exemple :

```text
cost =
  abs(currentFret - previousFret) * fretWeight
  + abs(currentString - previousString) * stringWeight
  + highFretPenalty
```

Structure cette logique dans une classe/service indépendant et testable.

Exemple :

```text
BassFretboardSolver
```

Je veux pouvoir modifier les heuristiques plus tard sans toucher au moteur de transcription.

---

# 10. Polyphonie basse

Basic Pitch peut détecter de la polyphonie.

Pour le MVP :

* supporter correctement une ligne de basse monophonique ;
* conserver plusieurs notes simultanées si elles sont détectées ;
* ne pas planter ;
* documenter les limites du fretboard solver en cas d’accords ou double-stops.

Si nécessaire, traiter d’abord les lignes monophoniques de manière optimale et utiliser un fallback raisonnable pour la polyphonie.

---

# 11. Export MIDI basse

Créer un export :

```text
bass.mid
```

à partir de notre `NoteEvent[]`.

Le fichier MIDI doit inclure :

* notes ;
* positions temporelles ;
* durées ;
* vélocités ;
* tempo.

Utiliser un package Python fiable tel que `pretty_midi`, `mido`, ou équivalent.

Choisir l’option la plus simple et maintenable.

---

# 12. Export MIDI batterie

Créer :

```text
drums.mid
```

Utiliser le canal MIDI percussion standard si approprié.

Mapper nos `DrumInstrument` vers General MIDI.

Le tempo doit correspondre au `TempoMap`.

---

# 13. Export MusicXML basse

Créer :

```text
bass.musicxml
```

Le fichier doit contenir une vraie structure musicale :

* mesures ;
* tempo ;
* durées ;
* notes ;
* silences si nécessaire ;
* signature rythmique.

Pour le MVP, supporter principalement :

```text
4/4
```

mais ne pas hardcoder toute l’architecture autour de 4/4.

Si possible, inclure également :

* corde ;
* fret ;

dans les informations techniques MusicXML appropriées pour une tablature.

---

# 14. Export MusicXML batterie

Créer :

```text
drums.musicxml
```

Utiliser correctement la notation percussion MusicXML :

* portée percussion ;
* percussion non pitched ;
* différentes positions/têtes de notes lorsque pertinent ;
* mesures ;
* durées ;
* silences.

Le résultat doit pouvoir être ouvert correctement dans au moins :

* MuseScore ;
* Guitar Pro si son import MusicXML le permet.

---

# 15. Ne pas écrire Guitar Pro directement

Ne pas implémenter `.gp`, `.gp5`, `.gpx` pour l’instant.

Le workflow souhaité est :

```text
Stem Studio
   ↓
MusicXML
   ↓
MuseScore / Guitar Pro / Dorico / Sibelius
```

MIDI reste également disponible.

---

# 16. Frontend : bouton Transcribe

Dans la piste Bass :

```text
Bass
[M] [S] [volume] waveform
                     [Transcribe]
```

Même chose pour Drums.

Cliquer sur `Transcribe` doit :

1. vérifier que le stem existe ;
2. lancer le moteur Python ;
3. afficher un état de progression ;
4. recevoir les événements ;
5. les ajouter à l’état du projet ;
6. afficher une vue de transcription.

---

# 17. Progression

Le sidecar doit produire des événements JSON structurés.

Exemple :

```json
{
  "type": "transcription_progress",
  "track": "bass",
  "stage": "inference",
  "progress": 0.65
}
```

Stages possibles :

```text
loading_model
inference
beat_tracking
quantization
fretboard
export
completed
```

Pour drums :

```text
loading_model
inference
beat_tracking
quantization
export
completed
```

---

# 18. UI de transcription basse

Ajouter une section ou vue permettant d’afficher au minimum une tablature basse simple.

Exemple conceptuel :

```text
Bass transcription

   1            2            3            4

G|----------------|----------------|
D|-------5--7-----|----------------|
A|--5----------7--|--5-------------|
E|----------------|------7--5------|

[Export MIDI]
[Export MusicXML]
```

Cette vue n’a pas besoin d’être un moteur de gravure musicale professionnel dans le MVP.

Je veux surtout :

* une représentation claire ;
* mesure par mesure ;
* notes/cases visibles ;
* synchronisation avec la lecture.

---

# 19. UI batterie

Créer également une représentation simple des événements batterie.

Par exemple :

```text
HH | x-x-x-x-x-x-x-x-
SN | ----o-------o---
BD | o-------o-o-----
```

ou une représentation graphique similaire.

Il n’est pas nécessaire d’implémenter immédiatement une gravure complète de partition traditionnelle dans React.

MusicXML sera responsable de l’export de partition professionnelle.

---

# 20. Synchronisation avec le player

C’est une fonctionnalité importante.

La transcription doit être synchronisée avec le moteur audio déjà existant.

Quand l’utilisateur clique sur une note basse :

```text
seek(note.detectedStartSeconds)
```

Quand il clique sur un événement batterie :

```text
seek(event.detectedTimeSeconds)
```

Pendant la lecture, mettre en évidence la note ou l’événement courant si cela reste raisonnablement simple.

Ne duplique pas le moteur de transport audio existant.

Réutilise l’`AudioEngine` actuel.

---

# 21. Édition manuelle

Préparer l’architecture pour permettre plus tard de corriger une transcription.

Pour le MVP, si cela reste raisonnable, permettre au minimum :

### Bass

* déplacer légèrement une note ;
* changer son pitch ;
* changer sa durée ;
* changer corde/case.

### Drums

* déplacer un événement ;
* changer sa classe ;
* supprimer l’événement.

Si cela augmente trop le scope, construire au minimum les modèles et services pour que ces événements soient mutables dans le futur.

---

# 22. State management

Étendre l’état existant du projet.

Par exemple :

```ts
interface BassTranscription {
  status:
    | "idle"
    | "processing"
    | "ready"
    | "error"

  events: NoteEvent[]
  tab: TabNote[]

  tempoMap?: TempoMap
}

interface DrumTranscription {
  status:
    | "idle"
    | "processing"
    | "ready"
    | "error"

  events: DrumEvent[]

  tempoMap?: TempoMap
}
```

Ne mélange pas :

* état du mixer ;
* état de séparation ;
* état de transcription.

---

# 23. Cache des modèles

L’application utilise déjà un backend ML Python.

Pour les poids Basic Pitch et ADTOF :

ne pas les stocker dans `.venv`.

En production :

* runtime Python dans le sidecar ;
* modèles téléchargés ou stockés dans Application Support.

Par exemple :

```text
~/Library/Application Support/Stem Studio/models/
├── basic-pitch/
└── adtof/
```

Si la bibliothèque gère déjà un cache de modèles fiable, encapsuler proprement ce mécanisme.

Je veux éviter des téléchargements répétitifs.

---

# 24. Chargement des modèles

Éviter de recharger inutilement les modèles ML.

Si le moteur Python actuel fonctionne comme process persistant, conserver les modèles en mémoire.

Sinon, analyser si un process Python long-lived dédié au ML serait plus efficace.

Mais ne transforme pas l’architecture de façon disproportionnée pour ce MVP.

Priorité :

* simplicité ;
* stabilité ;
* temps de transcription acceptable.

---

# 25. Interface backend générique

Je veux que l’application ne dépende pas directement de Basic Pitch ou ADTOF.

Créer par exemple :

```text
TranscriptionEngine
├── BassTranscriber
│   └── BasicPitchBassTranscriber
│
└── DrumTranscriber
    └── AdtofDrumTranscriber
```

De cette façon on pourra plus tard remplacer un modèle.

---

# 26. CLI / protocole sidecar

Étendre la CLI existante.

Par exemple :

```bash
stem-engine transcribe-bass \
  "/path/bass.wav" \
  --output "/path/project/transcription"
```

et :

```bash
stem-engine transcribe-drums \
  "/path/drums.wav" \
  --output "/path/project/transcription"
```

Résultat final basse :

```json
{
  "type": "transcription_completed",
  "track": "bass",
  "result": {
    "eventsFile": ".../bass-transcription.json",
    "midiFile": ".../bass.mid",
    "musicXmlFile": ".../bass.musicxml"
  }
}
```

Résultat batterie :

```json
{
  "type": "transcription_completed",
  "track": "drums",
  "result": {
    "eventsFile": ".../drums-transcription.json",
    "midiFile": ".../drums.mid",
    "musicXmlFile": ".../drums.musicxml"
  }
}
```

---

# 27. Stockage projet

Stocker les données de transcription avec le projet.

Exemple :

```text
project/
├── vocals.wav
├── drums.wav
├── bass.wav
├── other.wav
│
└── transcription/
    ├── bass.json
    ├── bass.mid
    ├── bass.musicxml
    │
    ├── drums.json
    ├── drums.mid
    └── drums.musicxml
```

Le JSON doit rester la représentation interne persistée principale.

MIDI et MusicXML peuvent être régénérés.

---

# 28. Tests unitaires

Ajouter des tests sérieux.

## Bass

Tester :

* conversion pitch MIDI ;
* génération de positions possibles corde/case ;
* basse standard EADG ;
* Drop D ;
* rejet des notes impossibles ;
* coût de transition entre positions ;
* programmation dynamique du fretboard solver ;
* notes consécutives ;
* sauts importants ;
* export MIDI.

Exemple :

```text
MIDI 40 -> E2

positions EADG possibles :
E string fret 12
A string fret 7
D string fret 2
```

Le solver doit choisir une position cohérente avec le contexte précédent.

## Drums

Tester :

* mapping ADTOF -> DrumInstrument ;
* mapping DrumInstrument -> General MIDI ;
* kick ;
* snare ;
* closed/open hi-hat ;
* cymbals ;
* toms.

## Quantification

Tester :

* secondes -> beat ;
* quantification 1/4 ;
* quantification 1/8 ;
* quantification 1/16 ;
* conservation du timestamp original.

## MusicXML

Tester au minimum :

* document XML valide ;
* mesures créées ;
* notes créées ;
* tempo présent ;
* fichiers lisibles par une bibliothèque XML standard.

---

# 29. Test manuel avec MuseScore

Documenter une procédure de validation :

```text
1. importer un morceau ;
2. générer les stems ;
3. transcrire bass ;
4. exporter bass.musicxml ;
5. ouvrir dans MuseScore ;
6. vérifier notes / mesures / tempo ;
7. écouter avec l'original.

8. transcrire drums ;
9. exporter drums.musicxml ;
10. ouvrir dans MuseScore ;
11. vérifier kick/snare/hihat.
```

Faire la même validation avec MIDI.

---

# 30. Gestion des erreurs

Afficher des erreurs propres :

```text
Bass transcription failed.
Drum transcription failed.
Unable to load transcription model.
Unable to detect tempo reliably.
Unable to export MusicXML.
```

Ne jamais afficher directement une stack trace Python à l’utilisateur.

Les détails restent dans les logs.

---

# 31. Limitations à documenter

Le README doit expliquer clairement que la transcription audio musicale est probabiliste.

Exemples de limites :

* notes fantômes ;
* slides ;
* hammer-on / pull-off ;
* notes très courtes ;
* slap bass ;
* accords basse ;
* double kick rapide ;
* ghost notes batterie ;
* cymbales superposées ;
* tempo non constant ;
* swing ;
* changements de signature.

Ne cherche pas à résoudre tous ces problèmes dans le MVP.

---

# 32. Scope MVP

Priorité absolue :

```text
bass.wav
→ Basic Pitch
→ NoteEvent[]
→ beat tracking
→ quantification
→ fretboard solver
→ MIDI
→ MusicXML
→ tablature simple
```

Puis :

```text
drums.wav
→ ADTOF
→ DrumEvent[]
→ beat tracking
→ quantification
→ MIDI
→ MusicXML
→ drum grid simple
```

---

# 33. Hors scope

Ne pas implémenter maintenant :

* reconnaissance d’accords complète ;
* guitare ;
* piano ;
* voix ;
* génération automatique de doigtés avancés ;
* techniques de jeu basse ;
* slides/hammer/pull-off automatiques ;
* notation batterie ultra détaillée ;
* export Guitar Pro natif ;
* moteur complet de notation musicale ;
* apprentissage/fine-tuning de modèles IA ;
* cloud inference.

---

# 34. Qualité attendue

Je veux :

* code réellement intégré à l’application existante ;
* pas un prototype séparé ;
* séparation claire ML / domaine musical / UI ;
* TypeScript strict ;
* Python typé lorsque pertinent ;
* services testables ;
* erreurs structurées ;
* JSON stable entre Python et Tauri ;
* pas de dépendance UI directe à Basic Pitch ou ADTOF ;
* pas de duplication du transport audio ;
* pas de hardcoding inutile de l’accordage ou des mappings MIDI.

---

# 35. Méthode de travail

Commence par examiner le repository existant afin de comprendre :

* architecture actuelle ;
* sidecar Python ;
* protocole JSON ;
* AudioEngine ;
* state management ;
* système de projet ;
* séparation des stems.

Ne recrée pas l’application depuis zéro.

Ensuite :

1. propose brièvement les modifications d’architecture ;
2. ajoute les modèles de domaine de transcription ;
3. implémente Basic Pitch pour la basse ;
4. implémente le beat tracking ;
5. implémente la quantification ;
6. implémente le fretboard solver ;
7. implémente les exports MIDI/MusicXML basse ;
8. branche cela dans Tauri et React ;
9. implémente l’UI basse ;
10. implémente ADTOF pour drums ;
11. implémente les mappings drums ;
12. implémente les exports MIDI/MusicXML batterie ;
13. implémente l’UI batterie ;
14. ajoute les tests ;
15. lance lint/typecheck/tests/build ;
16. corrige les erreurs jusqu’à avoir un flux fonctionnel.

Ne t’arrête pas après avoir créé les interfaces et TODOs.

Je veux au minimum un flux basse de bout en bout réellement fonctionnel, puis le maximum raisonnable sur la batterie.

---

# 36. Vérification finale

À la fin, donne-moi :

* résumé des fonctionnalités implémentées ;
* architecture retenue ;
* fichiers principaux créés/modifiés ;
* nouvelles dépendances Python et JS ;
* commandes d’installation ;
* procédure pour tester la basse ;
* procédure pour tester la batterie ;
* procédure pour ouvrir les exports dans MuseScore ;
* limitations connues ;
* éventuels problèmes de packaging macOS ;
* prochaines améliorations recommandées.

Priorité générale :

**qualité et modularité du pipeline musical > sophistication visuelle de l’éditeur de partition.**
