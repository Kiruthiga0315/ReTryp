import { Link } from "react-router-dom";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/States";
import { PageHeader } from "../components/layout/AppShell";

export function NotFoundPage() {
  return (
    <>
      <PageHeader title="Page not found" />
      <Card>
        <EmptyState icon="Compass" title="That page does not exist">
          The link may be out of date, or the page may have moved. Everything ReTryp offers is
          reachable from the sidebar.
          <div className="row row-2" style={{ marginTop: "var(--s-3)", justifyContent: "center" }}>
            <Link to="/" className="btn btn--primary">
              Back to dashboard
            </Link>
            <Link to="/recovery" className="btn">
              Recovery Center
            </Link>
          </div>
        </EmptyState>
      </Card>
    </>
  );
}
