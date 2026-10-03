---
description: register, EXTRACTORS, pages_matching, parse_pages and fit_page_boxes.
---

# Engines and pages

```{eval-rst}
.. autofunction:: pdfexorcist.register
```

```{eval-rst}
.. py:data:: pdfexorcist.EXTRACTORS
   :type: dict[str, Callable[[Path], Iterator[Page]]]

   Every registered engine by name: the built-in ones and any added with
   :func:`~pdfexorcist.register`. An engine takes a PDF path and yields
   ``(page_no, lines)``.
```

```{eval-rst}
.. autofunction:: pdfexorcist.pages_matching
```

```{eval-rst}
.. autofunction:: pdfexorcist.parse_pages
```

```{eval-rst}
.. autofunction:: pdfexorcist.fit_page_boxes
```
