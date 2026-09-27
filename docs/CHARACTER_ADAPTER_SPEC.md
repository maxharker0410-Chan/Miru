# Character Adapter Specification

Status: Draft for Companion V1  
Target: Windows desktop pet first  
Compatibility: Existing Miru behavior must remain the default

## Purpose

Miru's current pet renderer is implemented directly in `templates/pet.html`
and assumes a bundled Live2D Hiyori model. Companion V1 needs a stable boundary
between Miru Core events and the visual character implementation so that the
renderer can later use Live2D, DragonBones, or a sprite sequence without
changing memory, chat, attention, or emotion logic.

## Boundary

The adapter owns visual character behavior only:

- load and unload a character asset;
- enter a named animation state;
- apply an expression or emotion;
- look toward a normalized screen point;
- report visual bounds for click-through and dragging;
- resize or re-layout the character;
- expose renderer capabilities.

The adapter must not own:

- prompts, personality, memory, or journaling;
- model API calls;
- user authentication or device sync;
- microphone or screen-capture permissions;
- room navigation policy.

## Proposed interface

```ts
type CharacterState =
  | "idle"
  | "thinking"
  | "talking"
  | "walking-left"
  | "walking-right"
  | "happy"
  | "sad"
  | "surprised"
  | "sleeping";

type CharacterCapabilities = {
  motions: boolean;
  expressions: boolean;
  lipSync: boolean;
  focusTracking: boolean;
  transparentBackground: boolean;
};

type CharacterBounds = {
  left: number;
  top: number;
  right: number;
  bottom: number;
};

interface CharacterAdapter {
  readonly id: string;
  readonly capabilities: CharacterCapabilities;

  mount(host: HTMLElement, options: CharacterMountOptions): Promise<void>;
  unmount(): Promise<void>;
  setState(state: CharacterState, payload?: unknown): Promise<void>;
  setEmotion(emotion: string, intensity?: number): Promise<void>;
  lookAt(x: number, y: number): void;
  resize(width: number, height: number, layout: CharacterLayout): void;
  getBounds(): CharacterBounds | null;
}
```

Coordinates passed to `lookAt` are normalized to `[-1, 1]`. Layout values are
renderer-neutral and converted inside each adapter.

## State rules

1. `talking` temporarily overrides `idle` but not a critical `sleeping` state.
2. `thinking` ends when a response arrives, a request fails, or a timeout is
   reached.
3. Walking states are controlled by the room layer, not by the language model.
4. Emotion changes may select an expression while preserving the current
   movement state.
5. Unsupported states must fall back to `idle`; they must not throw or freeze
   the pet window.

## Event mapping

The initial event bridge now sends `thinking` on message submission, `talking`
on a newly detected assistant reply, and `idle` on request failure or timeout.
Because the pet receives complete messages through polling, `talking` currently
lasts 1.5–8 seconds based on text length; this is not audio synchronization.
Thinking has a 120-second watchdog that repeated polls cannot extend.
Emotion is read from `/api/miru-emotion/current` every 15 seconds, independently
of conversation state. Sleeping takes priority over conversation events.
The existing Live2D adapter now uses `live2d-motion-bridge.js` to resolve declared
motion groups (Idle, Think/Thinking, Talk/Talking, Sleep/Sleeping, walking and
emotion names) and named expressions. Matching is case-insensitive. Unknown
states fall back to the declared Idle group; unknown emotions select Neutral
or reset the expression. No numbered sample clip is guessed to mean an emotion.
Motions declaring audio are skipped. Emotion intensity is not blended by this
initial bridge. Model capabilities are refreshed after successful mounting.
The repository does not include the installed Hiyori model: visible results
depend on its actual named groups and require Windows validation.

API reference: https://guansss.github.io/pixi-live2d-display/motions_expressions/

| Miru event | Character action |
|---|---|
| User sends a message | `thinking` |
| Assistant text begins | `talking` |
| Assistant text ends | `idle` plus current emotion |
| Attention Engine activates | short attention motion, then prior state |
| Emotion API changes | `setEmotion(name, intensity)` |
| Room target is left/right | matching walking state |
| Quiet or sleep mode | `sleeping` |

## Adapter implementations

### Existing Live2D adapter

- Wrap the current PIXI and `pixi-live2d-display` code.
- Preserve focus tracking, model bounds, layout persistence, and transparent
  background behavior.
- Continue to use the bundled model only as a local development baseline.
- Do not redistribute Live2D Core, Cubism frameworks, or sample model data
  under the repository's Apache-2.0 license.

### DragonBones adapter

- Load a DragonBones skeleton, texture atlas, and textures from an explicitly
  configured character package.
- Map generic state names to animation clip names through a manifest.
- Keep the same anchor and bounds contract as the Live2D adapter.

### Sprite adapter

- Support PNG sequences, spritesheets, or GIF/WebP fallback assets.
- Use a manifest for frame rate, loop behavior, direction, and anchor point.
- Serve as the lowest-complexity renderer for early room movement tests.

## Character package manifest

```json
{
  "schemaVersion": 1,
  "id": "companion-character",
  "renderer": "dragonbones",
  "entry": "character_ske.json",
  "atlas": "character_tex.json",
  "textures": ["character_tex.png"],
  "anchor": { "x": 0.5, "y": 1.0 },
  "states": {
    "idle": "idle",
    "thinking": "thinking",
    "talking": "talk",
    "walking-left": "walk_left",
    "walking-right": "walk_right",
    "sleeping": "sleep"
  },
  "emotions": {
    "happy": "happy",
    "sad": "sad",
    "surprised": "surprised"
  }
}
```

The manifest must contain no executable code and must not reference files
outside its own character package directory.

## Migration sequence

1. Add an adapter facade without changing the current Live2D behavior.
2. Move model load, focus tracking, layout, and bounds code behind the Live2D
   adapter.
3. Add state events for thinking, talking, and emotion.
4. Add a Sprite adapter for room movement prototyping.
5. Add DragonBones only after the common contract passes the same tests.
6. Remove direct model assumptions from `templates/pet.html` after parity is
   confirmed on Windows.

## Acceptance tests

- Loading an unsupported state falls back to `idle`.
- Repeated `mount` and `unmount` calls do not leak canvases or listeners.
- Adapter failure leaves text chat usable.
- Character bounds remain valid after window resize and layout changes.
- Focus tracking is disabled when the renderer does not support it.
- No adapter may enable microphone or screen capture.
- Existing Live2D desktop behavior remains unchanged until migration parity is
  demonstrated.
