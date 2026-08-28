# Audit de Stem Studio

**Verdict : le projet est une alpha solide et réellement fonctionnelle**, avec une interface convaincante et une architecture saine. La séparation par les deux modèles fonctionne. En revanche, il reste plusieurs blocages avant une diffusion publique ou un usage musical fiable, principalement autour de la quantification, de MusicXML, du packaging et des licences.

| Fonction | État | Conclusion |
|---|---|---|
| Séparation en 4 stems | ✅ | Standard Demucs et High BS-RoFormer fonctionnent |
| Analyse fréquentielle | ⚠️ | Fonctionnelle, mais limitée au canal gauche |
| Transcription basse | ⚠️ | Pipeline opérationnel, mais erreurs possibles avant le premier temps |
| Transcription batterie | ⚠️ | DrumScript fonctionne, export MusicXML à corriger |
| Export MIDI | ⚠️ | Produit des fichiers, mais peut créer des notes simultanées en double |
| Export MusicXML | ❌ | Pas encore musicalement fiable |
| Sessions portables | ⚠️ | Bonne base, validation insuffisante à l’import |

## Points forts

- Architecture claire : React/TypeScript, Tauri/Rust et moteur Python bien séparés.
- TypeScript strict et modèles métier propres.
- Validation sérieuse des chemins, écritures atomiques et permissions Tauri réduites.
- Fallback MPS vers CPU implémenté et testé.
- Les deux moteurs de séparation ont réussi un essai réel de 15 secondes :
  - Standard : environ 10 s ;
  - High : environ 36,6 s.
- Interface propre, responsive et sans erreur console lors du contrôle visuel.
- Le mixeur, le spectrogramme, la navigation depuis la tablature et les événements de batterie fonctionnent.

Ces essais valident l’exécution des pipelines, mais pas encore la qualité audio comparative des modèles.

## Blocages prioritaires

### 1. Quantification et MusicXML incorrects

C’est le principal problème fonctionnel.

Le premier beat détecté devient arbitrairement le beat zéro, sans recherche du premier temps de la mesure. Les événements antérieurs produisent une position négative ensuite ramenée à zéro dans [quantization.py](/Users/fabricecoroller/Documents/workspace/demuxer/engine/quantization.py:13) et [beat_tracker.py](/Users/fabricecoroller/Documents/workspace/demuxer/engine/beat_tracker.py:24).

Lors de l’essai réel :

- deux notes de basse distinctes ont été regroupées au beat zéro ;
- le MIDI contenait deux `note-on` identiques au même tick ;
- la première mesure MusicXML contenait **19 divisions au lieu de 16** pour une mesure 4/4 ;
- les notes traversant une barre de mesure sont tronquées, sans liaison ;
- certaines durées pointées sont déclarées comme des durées simples ;
- la batterie utilise un unique instrument MIDI correspondant à la grosse caisse pour tout le kit.

Les causes principales sont dans [musicxml_export.py](/Users/fabricecoroller/Documents/workspace/demuxer/engine/musicxml_export.py:38). Les tests actuels vérifient surtout que le XML est lisible, pas qu’il respecte rythmiquement les mesures ou survive à un aller-retour dans MuseScore.

**Recommandation :** introduire une représentation temporelle canonique, détecter les downbeats, normaliser les chevauchements, scinder les notes aux barres de mesure avec des ties, puis tester les exports dans MuseScore.

### 2. Démarrage très lent du moteur packagé

Le sidecar PyInstaller fait environ 230 Mo, utilise un bundle « one-file » dans [stem-engine.spec](/Users/fabricecoroller/Documents/workspace/demuxer/engine/stem-engine.spec:45), puis est relancé pour chaque séparation ou transcription dans [lib.rs](/Users/fabricecoroller/Documents/workspace/demuxer/app/src-tauri/src/lib.rs:402).

Sur une transcription de 15 secondes :

- environnement Python : environ 5,7 s ;
- sidecar packagé : environ 46 s ;
- près de 30 s avant le premier progrès visible.

**Recommandation :** passer à un bundle `onedir` ou, mieux, conserver un moteur Python résident. Il faut également afficher un état de démarrage immédiatement après le lancement.

### 3. Conformité des composants distribués

Le script embarque le premier FFmpeg disponible dans [package-engine.sh](/Users/fabricecoroller/Documents/workspace/demuxer/scripts/package-engine.sh:30). Celui présent dans le workspace est construit avec `--enable-gpl`, x264 et x265, alors qu’aucune licence ou notice tierce n’est fournie.

La documentation officielle précise que l’activation de composants GPL fait basculer FFmpeg sous GPL et recommande une compilation sans ces options pour rester sur le chemin LGPL : [guide juridique officiel de FFmpeg](https://ffmpeg.org/legal.html).

Le README indique aussi que la licence du checkpoint BS-RoFormer n’a pas encore été vérifiée.

**Conclusion :** une revue de conformité est indispensable avant toute redistribution commerciale. Ce constat n’est pas un avis juridique.

### 4. Sessions insuffisamment validées

Rust accepte le contenu transcription comme un simple `serde_json::Value` dans [lib.rs](/Users/fabricecoroller/Documents/workspace/demuxer/app/src-tauri/src/lib.rs:877), tandis que React suppose ensuite que toute la structure est valide.

Une session syntaxiquement correcte mais incomplète peut donc faire planter l’espace de transcription.

**Recommandation :** définir des structures Rust typées, valider `schemaVersion`, pistes, plages temporelles et fichiers associés, puis ajouter une validation runtime côté TypeScript.

### 5. Mémoire et stockage non bornés

Les quatre stems complets sont téléchargés et décodés simultanément dans [AudioEngine.ts](/Users/fabricecoroller/Documents/workspace/demuxer/app/src/audio/AudioEngine.ts:59). Le moteur Python charge également tout le PCM en mémoire dans [audio_io.py](/Users/fabricecoroller/Documents/workspace/demuxer/engine/audio_io.py:50).

Pour un morceau de 5 min 40, les quatre buffers Float32 stéréo représentent déjà environ 477 Mo, sans compter les copies, le spectrogramme et le modèle.

Par ailleurs, les dossiers temporaires ne sont pas supprimés après succès, erreur ou annulation. Les sessions sauvegardées dupliquent encore les WAV.

**Recommandation :** limites explicites de durée/taille, décodage en flux ou par fenêtres, cache borné et stratégie de nettoyage automatique.

## Autres écarts

- L’analyse fréquentielle exclut explicitement `drums` dans [types.ts](/Users/fabricecoroller/Documents/workspace/demuxer/app/src/domain/types.ts:2) et n’analyse que le premier canal.
- Le profil sauvegardé peut être faux : l’utilisateur peut séparer en Standard, sélectionner ensuite High, puis enregistrer une session étiquetée High dans [App.tsx](/Users/fabricecoroller/Documents/workspace/demuxer/app/src/App.tsx:118).
- `App` souscrit au store Zustand complet tandis que l’horloge est mise à jour à chaque frame, ce qui peut provoquer un rerendu global à environ 60 Hz dans [App.tsx](/Users/fabricecoroller/Documents/workspace/demuxer/app/src/App.tsx:44).
- À 700 × 520, la dernière piste du mixeur déborde d’environ 6 px sur le transport.
- Le workspace observé pèse environ 8,4 Go et contient les targets Rust, environnements Python, builds du moteur et binaires. Le [.gitignore](/Users/fabricecoroller/Documents/workspace/demuxer/.gitignore:1) ne couvre pas plusieurs de ces éléments.
- Les dépendances Python sont déclarées par plages, sans lockfile ni hashes reproductibles.

## Vérifications effectuées

- **88 tests automatisés réussis** :
  - 31 frontend ;
  - 52 Python ;
  - 5 Rust.
- Build TypeScript/Vite réussi.
- `cargo fmt --check`, `cargo check` et `cargo test` réussis.
- Validation syntaxique des scripts shell réussie.
- Essais réels réussis pour Standard, High, Basic Pitch et DrumScript.
- La couverture frontend ne démarre pas : dépendance `@vitest/coverage-v8` absente.
- Aucun CI, linter frontend, type checker Python, SBOM ou inventaire de licences détecté.

## Feuille de route recommandée

1. **Fiabilité musicale** : downbeats, chevauchements, mesures, ties, durées pointées et instruments batterie.
2. **Robustesse** : validation des sessions, tests MuseScore et tests end-to-end du sidecar packagé.
3. **Performance** : moteur résident, progrès immédiat, nettoyage disque et limites mémoire.
4. **Distribution** : audit FFmpeg/checkpoints, licences, CI, lockfiles et packaging signé/notarisé.
5. **Complétude produit** : spectrogramme Drums, analyse stéréo et mémorisation réelle du modèle employé.
