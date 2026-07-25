import { redirect } from "next/navigation";

// The bare "/" route just forwards to the dashboard, which itself
// bounces to /login when there is no session.
export default function Home() {
  redirect("/dashboard");
}
