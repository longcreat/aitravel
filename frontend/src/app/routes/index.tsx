import { createBrowserRouter } from "react-router-dom";
import ChatPage from "@/pages/chat";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <ChatPage />,
  },
  {
    path: "/chat",
    element: <ChatPage />,
  },
]);
