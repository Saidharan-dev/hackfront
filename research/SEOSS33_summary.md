1. Paper: Rath & Mader (2019), **“The SEOSS 33 dataset — Requirements, bug reports, code history, and trace links for entire projects.”**
2. Main purpose: **release and document a public dataset**, not propose a new traceability/linking algorithm.
3. Dataset covers **33 open-source projects**, combining Jira issue data and Git version-control history.
4. It provides roughly **300k issue artifacts, 350k commits/source-code artifacts, and 200k trace links**.
5. Data is stored per project in a **SQLite relational database** with 8 main tables + 1 metadata table.
6. Important units/artifacts: **issues, issue links, comments, components, versions, commits, commit–issue links, and code changes**.
7. Issue→issue relations are taken from **existing Jira trace links** (e.g., relates-to, duplicate, reference).
8. Issue→commit relations are created by **finding Jira issue IDs in Git commit messages**.
9. Commit→code relations come from the **files/code changes contained in each Git commit**.
10. Thus the basic chain is: **Issue/Requirement/Bug → Commit → Changed File/Code**.
11. The linking principle is primarily **explicit/reference-based traceability**, not semantic inference or ML.
12. Their relations are therefore mostly **straightforward, low-level artifact-to-artifact links**.
13. They do **not propose a new ontology or theory for naming relationships between artifacts**.
14. They also do **not develop higher-order/semantic relations** between artifacts; the dataset is intended as infrastructure/benchmark data.
15. Key takeaway for our research: **SEOSS 33 is a useful baseline/data source, but not a methodology for defining richer or higher-order artifact relationships.**