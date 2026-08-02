import { useEffect, useState } from "react";

function readMatch(query: string): boolean {
  return typeof window !== "undefined" && window.matchMedia(query).matches;
}

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => readMatch(query));

  useEffect(() => {
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [query]);

  return matches;
}
