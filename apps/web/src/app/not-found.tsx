import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Страница не найдена" };

export default function NotFound() {
  return (
    <main className="nf">
      <picture className="nf-art">
        <source srcSet="/brand/chobra-404.webp" type="image/webp" />
        <img src="/brand/chobra-404.png" width={1221} height={622} alt="404: кобра свернулась в ноль между двумя четверками" />
      </picture>
      <h1 className="nf-title">Здесь ничего нет</h1>
      <p className="nf-text">Ссылка устарела или адрес набран с ошибкой. Если вы открывали проект, запуск или отчет, возможно, у вас больше нет к нему доступа.</p>
      <div className="nf-actions">
        <Link href="/" className="btn btn-primary">
          К проектам
        </Link>
      </div>
    </main>
  );
}
