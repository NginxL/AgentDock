import { useState, type Dispatch, type SetStateAction } from "react";

/** Related form fields share one draft; field updates never replace other edits. */
export function useDraft<T extends object>(initial: T) {
  const [values, setValues] = useState(initial);
  const set =
    <K extends keyof T>(key: K): Dispatch<SetStateAction<T[K]>> =>
    (value) =>
      setValues((current) => ({
        ...current,
        [key]:
          typeof value === "function"
            ? (value as (previous: T[K]) => T[K])(current[key])
            : value,
      }));
  return { values, set };
}
