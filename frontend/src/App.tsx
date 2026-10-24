import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router";

import { AppRoutes } from "./routes";

export const makeQueryClient = () =>
  new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });

export function App({ client = makeQueryClient() }: { client?: QueryClient }) {
  return (
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
