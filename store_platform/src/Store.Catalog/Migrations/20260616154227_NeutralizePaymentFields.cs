using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace Store.Catalog.Migrations
{
    /// <inheritdoc />
    public partial class NeutralizePaymentFields : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "IX_SalesAudits_PaddleTransactionId",
                table: "SalesAudits");

            migrationBuilder.DropIndex(
                name: "IX_Orders_PaddleTransactionId",
                table: "Orders");

            migrationBuilder.RenameColumn(
                name: "PaddleTransactionId",
                table: "SalesAudits",
                newName: "ProviderTransactionId");

            migrationBuilder.RenameColumn(
                name: "PaddleProductId",
                table: "SalesAudits",
                newName: "ProviderProductId");

            migrationBuilder.RenameColumn(
                name: "PaddleProductId",
                table: "Packs",
                newName: "ProviderProductId");

            migrationBuilder.RenameColumn(
                name: "PaddlePriceId",
                table: "Packs",
                newName: "ProviderPriceId");

            migrationBuilder.RenameColumn(
                name: "PaddleTransactionId",
                table: "Orders",
                newName: "ProviderTransactionId");

            migrationBuilder.AddColumn<string>(
                name: "PaymentProvider",
                table: "SalesAudits",
                type: "TEXT",
                nullable: false,
                defaultValue: "paddle");

            migrationBuilder.AddColumn<string>(
                name: "PaymentProvider",
                table: "Packs",
                type: "TEXT",
                nullable: false,
                defaultValue: "paddle");

            migrationBuilder.AddColumn<string>(
                name: "PaymentProvider",
                table: "Orders",
                type: "TEXT",
                nullable: false,
                defaultValue: "paddle");

            migrationBuilder.CreateIndex(
                name: "IX_SalesAudits_PaymentProvider_ProviderTransactionId",
                table: "SalesAudits",
                columns: new[] { "PaymentProvider", "ProviderTransactionId" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_Orders_PaymentProvider_ProviderTransactionId",
                table: "Orders",
                columns: new[] { "PaymentProvider", "ProviderTransactionId" });
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "IX_SalesAudits_PaymentProvider_ProviderTransactionId",
                table: "SalesAudits");

            migrationBuilder.DropIndex(
                name: "IX_Orders_PaymentProvider_ProviderTransactionId",
                table: "Orders");

            migrationBuilder.DropColumn(
                name: "PaymentProvider",
                table: "SalesAudits");

            migrationBuilder.DropColumn(
                name: "PaymentProvider",
                table: "Packs");

            migrationBuilder.DropColumn(
                name: "PaymentProvider",
                table: "Orders");

            migrationBuilder.RenameColumn(
                name: "ProviderTransactionId",
                table: "SalesAudits",
                newName: "PaddleTransactionId");

            migrationBuilder.RenameColumn(
                name: "ProviderProductId",
                table: "SalesAudits",
                newName: "PaddleProductId");

            migrationBuilder.RenameColumn(
                name: "ProviderProductId",
                table: "Packs",
                newName: "PaddleProductId");

            migrationBuilder.RenameColumn(
                name: "ProviderPriceId",
                table: "Packs",
                newName: "PaddlePriceId");

            migrationBuilder.RenameColumn(
                name: "ProviderTransactionId",
                table: "Orders",
                newName: "PaddleTransactionId");

            migrationBuilder.CreateIndex(
                name: "IX_SalesAudits_PaddleTransactionId",
                table: "SalesAudits",
                column: "PaddleTransactionId",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_Orders_PaddleTransactionId",
                table: "Orders",
                column: "PaddleTransactionId");
        }
    }
}
