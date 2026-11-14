import { useEffect, useRef } from 'react';

// Escape has exactly one owner: the topmost layer that is open. Every layer
// registers here instead of adding its own unconditional window listener, so an
// Escape closes the detail modal without also collapsing the Surprise Me pane
// underneath it, and the next Escape closes that pane.
const layers = [];

export function __resetEscapeLayersForTests() {
  layers.length = 0;
}

export function activeEscapeLayers() {
  return layers.length;
}

export default function useEscapeLayer(active, onEscape) {
  const handlerRef = useRef(onEscape);

  useEffect(() => {
    handlerRef.current = onEscape;
  }, [onEscape]);

  useEffect(() => {
    if (!active) return undefined;

    const layer = {};
    layers.push(layer);

    const handleKeyDown = (event) => {
      if (event.key !== 'Escape') return;
      if (layers[layers.length - 1] !== layer) return;
      event.stopPropagation();
      if (handlerRef.current) handlerRef.current(event);
    };

    window.addEventListener('keydown', handleKeyDown);

    return () => {
      const index = layers.indexOf(layer);
      if (index >= 0) layers.splice(index, 1);
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [active]);
}
