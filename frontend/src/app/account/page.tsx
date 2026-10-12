import { AccountSettings } from "../../components/account-settings";
import { RequireAuth } from "../../components/auth";

export default function AccountPage() {
  return <RequireAuth><AccountSettings /></RequireAuth>;
}
