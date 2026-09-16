import { useEffect, useState } from "react";

/**
 * Which page is showing, kept in the URL's hash.
 *
 * `#/recovery` rather than a real route because this is a single file served from
 * anywhere -- a hash never reaches the server, so it works from Vite, from a static
 * bucket and from a file:// URL alike, and the back button and a bookmark both work.
 * A routing library would give the same thing with a dependency to learn.
 */

export const PAGES = ["overview", "energy", "recovery", "activity", "body", "log"] as const;

export type Page = (typeof PAGES)[number];

function readPageFromHash(): Page {
  const hash = window.location.hash.replace(/^#\/?/, "");

  for (const page of PAGES) {
    if (page === hash) {
      return page;
    }
  }

  return "overview";
}

export function usePage(): [Page, (next: Page) => void] {
  const [page, setPage] = useState<Page>(readPageFromHash);

  useEffect(() => {
    function onHashChange() {
      setPage(readPageFromHash());
    }

    window.addEventListener("hashchange", onHashChange);

    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  // A new page starts at its top. Done here, after the page has changed, rather than in
  // the hash handler, because the browser may restore the old scroll position itself
  // after that handler runs. "instant" overrides the page's smooth scrolling for this
  // one jump -- animating from the bottom of one page to the top of another looks like
  // a glitch rather than a transition.
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" });
  }, [page]);

  function go(next: Page) {
    window.location.hash = `/${next}`;
  }

  return [page, go];
}

export function hrefFor(page: Page): string {
  return `#/${page}`;
}
