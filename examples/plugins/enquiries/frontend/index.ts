const enquiries = {
  name: "enquiries",
  pages: {
    "": () => import("./enquiries-page"),
  },
  // The source (en) is required; other languages are optional and fall back to it key by key.
  messages: {
    en: () => import("./messages/en.json"),
  },
};

export default enquiries;
