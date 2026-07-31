using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Store.Catalog.Migrations
{
    /// <inheritdoc />
    public partial class DropAnalyticsSessionId : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            // Dropping the column IS the purge: the ids collected while the first cut of the
            // beacon was live go with it. That is intended, not collateral.
            //
            // Hand-written rather than migrationBuilder.DropColumn, and the reason is not
            // style. DropColumn makes EF rebuild the table (create temp, copy, drop, rename),
            // which SQLite cannot run inside a transaction — EF says so itself: "the migration
            // will be left in a partially applied state and would need to be reverted
            // manually". Migrations run at startup via MigrateAsync, so a process killed
            // mid-rebuild does not degrade analytics, it stops the API booting, and the store
            // is down until someone repairs the database by hand. SQLite has had atomic
            // ALTER TABLE ... DROP COLUMN since 3.35 (runtime here is 3.40) and the column
            // carries no index, which is the one thing that would block it. One statement,
            // no temp table, nothing to leave half-done.
            migrationBuilder.Sql("""ALTER TABLE "AnalyticsEvents" DROP COLUMN "SessionId";""");

            // Collapse any pre-existing duplicates before the unique index goes on. Migrations
            // run inside MigrateAsync at startup, so an index that cannot be built does not
            // degrade analytics — it stops the API from booting at all. The window where
            // double-counted purchases could have been written is small but it is not zero,
            // and "small" is not something to bet a live checkout rail on.
            migrationBuilder.Sql(
                """
                DELETE FROM "AnalyticsEvents"
                WHERE "Name" = 'checkout_completed'
                  AND "Meta" IS NOT NULL
                  AND "Id" NOT IN (
                      SELECT MIN("Id") FROM "AnalyticsEvents"
                      WHERE "Name" = 'checkout_completed' AND "Meta" IS NOT NULL
                      GROUP BY "Meta"
                  );
                """);

            migrationBuilder.CreateIndex(
                name: "IX_AnalyticsEvents_Name_Meta",
                table: "AnalyticsEvents",
                columns: new[] { "Name", "Meta" },
                unique: true,
                filter: "\"Name\" = 'checkout_completed' AND \"Meta\" IS NOT NULL");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "IX_AnalyticsEvents_Name_Meta",
                table: "AnalyticsEvents");

            migrationBuilder.AddColumn<string>(
                name: "SessionId",
                table: "AnalyticsEvents",
                type: "TEXT",
                maxLength: 64,
                nullable: true);
        }
    }
}
