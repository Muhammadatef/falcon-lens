import CheckForm from "./CheckForm";

export default function Home() {
  return (
    <main>
      <h1>عدسة الصقر</h1>
      <p className="lead">افحص أي رابط أو رسالة مشبوهة قبل أن تفتحها أو تردّ عليها.</p>
      <CheckForm />
      <p className="caution">لا تشارك بياناتك البنكية أو رقم هويتك مع أي جهة عبر رابط أو رسالة.</p>
    </main>
  );
}
